from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_current_user, get_session
from app.models import RefreshToken, TrialIdentity, User, UserConsent
from app.schemas import (
    ConsentAcceptRequest,
    ConsentRead,
    ConsentStatusResponse,
    LoginRequest,
    RefreshResponse,
    Token,
    UserCreate,
    UserRead,
)
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.trial import hash_email, hash_identity

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"


async def _issue_tokens(
    user_id: int,
    session: AsyncSession,
    response: Response,
) -> Token:
    """Выдаёт access-токен (в JSON) и refresh-токен (в httpOnly cookie)."""
    access_token = create_access_token(subject=user_id)

    refresh_token = generate_refresh_token()
    refresh_hash = hash_refresh_token(refresh_token)
    expires_at = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_expire_days)

    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=refresh_hash,
            expires_at=expires_at,
        )
    )
    await session.commit()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_refresh_expire_days * 24 * 3600,
        path="/auth",
        domain=settings.cookie_domain,
    )

    return Token(access_token=access_token)


@router.get("/check-email")
async def check_email(
    email: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Проверка: доступен ли email для регистрации.

    Возвращает {"available": bool}.
    Не раскрывает существование аккаунта — только доступность.
    """
    existing = await session.scalar(select(User).where(User.email == email))
    return {"available": existing is None}


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    existing = await session.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже зарегистрирован",
        )

    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    identity_hash = hash_identity(client_ip, user_agent)
    email_hash = hash_email(payload.email)

    identity_used = await session.scalar(
        select(TrialIdentity).where(TrialIdentity.identity_hash == identity_hash)
    )
    email_used = await session.scalar(
        select(TrialIdentity).where(TrialIdentity.email_hash == email_hash)
    )

    now = datetime.now(UTC)
    if identity_used is None and email_used is None:
        subscription_status = "trialing"
        trial_started_at = now
        trial_ends_at = now + timedelta(days=settings.trial_period_days)
    else:
        subscription_status = "none"
        trial_started_at = None
        trial_ends_at = None

    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        subscription_status=subscription_status,
        trial_started_at=trial_started_at,
        trial_ends_at=trial_ends_at,
    )
    session.add(user)
    await session.flush()

    if subscription_status == "trialing":
        session.add(
            TrialIdentity(
                identity_hash=identity_hash,
                email_hash=email_hash,
                user_id=user.id,
            )
        )

    # ФЗ-152: запись согласий на обработку ПДн и оферту
    for consent_type in ("pd_processing", "oferta"):
        session.add(
            UserConsent(
                user_id=user.id,
                consent_type=consent_type,
                ip_address=client_ip,
                user_agent=user_agent[:500] if user_agent else None,
            )
        )

    # ФЗ-152: сохранить user_id для AuditMiddleware
    request.state.user_id = user.id

    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Token:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    # ФЗ-152: сохранить user_id для AuditMiddleware
    request.state.user_id = user.id
    return await _issue_tokens(user.id, session, response)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    session: AsyncSession = Depends(get_session),
) -> RefreshResponse:
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )

    token_hash = hash_refresh_token(refresh_token)
    record = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if record is None or record.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    now = datetime.now(UTC)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    # Ротация: старый refresh отзываем, выдаём новый
    record.revoked = True
    await session.commit()

    tokens = await _issue_tokens(record.user_id, session, response)
    return RefreshResponse(access_token=tokens.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    session: AsyncSession = Depends(get_session),
) -> None:
    if refresh_token is not None:
        token_hash = hash_refresh_token(refresh_token)
        record = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if record is not None:
            record.revoked = True
            await session.commit()

    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/auth",
        domain=settings.cookie_domain,
    )


# ============================================================
# ФЗ-152: Согласия на обработку ПДн
# ============================================================


@router.get("/consent/status", response_model=ConsentStatusResponse)
async def consent_status(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentStatusResponse:
    """Статус всех согласий текущего пользователя."""
    result = await session.scalars(
        select(UserConsent)
        .where(UserConsent.user_id == current_user.id)
        .order_by(UserConsent.granted_at)
    )
    consents = [ConsentRead.model_validate(c) for c in result.all()]
    return ConsentStatusResponse(consents=consents)


@router.post("/consent/accept", response_model=ConsentRead)
async def consent_accept(
    payload: ConsentAcceptRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserConsent:
    """Принять согласие (или обновить после отзыва)."""
    # Ищем существующее согласие
    existing = await session.scalar(
        select(UserConsent).where(
            UserConsent.user_id == current_user.id,
            UserConsent.consent_type == payload.consent_type,
        )
    )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500] or None

    if existing is None:
        consent = UserConsent(
            user_id=current_user.id,
            consent_type=payload.consent_type,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        session.add(consent)
    else:
        # Обновляем: снимаем revoked_at, обновляем granted_at
        existing.revoked_at = None
        existing.granted_at = datetime.now(UTC)
        existing.ip_address = client_ip
        existing.user_agent = user_agent
        consent = existing

    await session.commit()
    await session.refresh(consent)
    return consent


@router.delete("/consent/{consent_type}", response_model=ConsentRead)
async def consent_revoke(
    consent_type: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserConsent:
    """Отозвать согласие (soft — фиксируем revoked_at)."""
    consent = await session.scalar(
        select(UserConsent).where(
            UserConsent.user_id == current_user.id,
            UserConsent.consent_type == consent_type,
        )
    )
    if consent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consent not found",
        )
    consent.revoked_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(consent)
    return consent
