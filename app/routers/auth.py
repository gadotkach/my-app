import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_current_user, get_session
from app.email_client import (
    send_email_verification_email,
    send_password_changed_email,
    send_password_reset_email,
)
from app.models import (
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    TrialIdentity,
    User,
    UserConsent,
)
from app.schemas import (
    ConsentAcceptRequest,
    ConsentRead,
    ConsentStatusResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RefreshResponse,
    ResendVerificationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    Token,
    UserCreate,
    UserRead,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.trial import hash_email, hash_identity
from app.yandex_oauth import (
    build_authorize_url,
    exchange_code,
    extract_email,
    extract_name,
    fetch_user_info,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
YANDEX_STATE_COOKIE_NAME = "yandex_oauth_state"
YANDEX_STATE_MAX_AGE = 600  # 10 минут

logger = logging.getLogger(__name__)


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

    # Email Verification: отправить письмо с токеном (best-effort)
    try:
        raw_token = await _create_email_verification_token(session, user)
        verify_url = f"{settings.frontend_base_url.rstrip('/')}" f"/verify-email?token={raw_token}"
        await send_email_verification_email(to=user.email, verify_url=verify_url)
    except Exception:
        logger.exception("Failed to send verification email to %s", user.email)

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


# ============================================================
# Яндекс ID (OAuth)
# ============================================================


@router.get("/yandex/redirect")
async def yandex_redirect(
    from_: str = "/",
) -> RedirectResponse:
    """Редирект на Яндекс ID для авторизации.

    Генерирует state, сохраняет его в HttpOnly cookie (CSRF-защита).
    """
    state = secrets.token_urlsafe(32)
    authorize_url = build_authorize_url(state)

    response = RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=YANDEX_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=YANDEX_STATE_MAX_AGE,
        path="/auth",
        domain=settings.cookie_domain,
    )
    return response


@router.get("/yandex/callback")
async def yandex_callback(
    request: Request,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    yandex_state: str | None = Cookie(default=None, alias=YANDEX_STATE_COOKIE_NAME),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Callback от Яндекса — обмен кода на токен, поиск/создание юзера, выдача JWT."""
    frontend_url = settings.frontend_base_url.rstrip("/")

    # Если пользователь отказался или Яндекс вернул ошибку
    if error or not code:
        return RedirectResponse(url=f"{frontend_url}/login?error=oauth_cancelled", status_code=302)

    # CSRF-защита: state из query vs state из cookie
    if not state or not yandex_state or state != yandex_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter (CSRF)",
        )

    # Обмен кода на access_token
    try:
        access_token = await exchange_code(code)
        user_info = await fetch_user_info(access_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Yandex OAuth error: {e!s}",
        ) from e

    email = extract_email(user_info)
    name = extract_name(user_info)
    yandex_id = str(user_info.get("id") or "")

    if not email or not yandex_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yandex did not provide email or id",
        )

    # Логика связки (A/B/C)
    # A. Уже есть юзер с таким yandex_id
    user = await session.scalar(select(User).where(User.yandex_id == yandex_id))

    if user is None:
        # B. Есть юзер с таким email — привязываем yandex_id
        user = await session.scalar(select(User).where(User.email == email))
        if user is not None:
            user.yandex_id = yandex_id
            await session.commit()
        else:
            # C. Новый юзер
            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "")

            user = User(
                email=email,
                name=name,
                hashed_password="",  # OAuth — без пароля
                yandex_id=yandex_id,
                subscription_status="trialing",
                trial_started_at=datetime.now(UTC),
                trial_ends_at=datetime.now(UTC) + timedelta(days=settings.trial_period_days),
            )
            session.add(user)
            await session.flush()

            # ФЗ-152: согласия
            for consent_type in ("pd_processing", "oferta"):
                session.add(
                    UserConsent(
                        user_id=user.id,
                        consent_type=consent_type,
                        ip_address=client_ip,
                        user_agent=user_agent[:500] if user_agent else None,
                    )
                )
            await session.commit()
            await session.refresh(user)

    # Выдача токенов (используем общий хелпер)
    request.state.user_id = user.id
    tokens = await _issue_tokens(user.id, session, response)

    # Редирект на фронт с access_token в fragment (не в query — чтобы не попадал в логи)
    redirect_url = f"{frontend_url}/auth/yandex/complete#access_token={tokens.access_token}"
    redirect = RedirectResponse(url=redirect_url, status_code=302)

    # Удаляем state cookie
    redirect.delete_cookie(
        key=YANDEX_STATE_COOKIE_NAME,
        path="/auth",
        domain=settings.cookie_domain,
    )
    # Переносим refresh cookie (её поставил _issue_tokens в `response`, но мы возвращаем `redirect`)
    if REFRESH_COOKIE_NAME in response.headers.get("set-cookie", ""):
        for header in response.headers.getlist("set-cookie"):
            redirect.headers.append("set-cookie", header)

    return redirect


# ============================================================
# Восстановление пароля
# ============================================================


def _hash_reset_token(token: str) -> str:
    """SHA-256 хеш токена для хранения в БД."""
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ForgotPasswordResponse:
    """Запрос на восстановление пароля.

    Всегда возвращает 200, чтобы не раскрывать существование аккаунта.
    Если email найден — создаёт токен (живёт 1 час) и отправляет письмо.
    """
    user = await session.scalar(select(User).where(User.email == payload.email))

    if user is not None and not user.deleted_at:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        expires_at = datetime.now(UTC) + timedelta(hours=1)

        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        await session.commit()

        reset_url = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={raw_token}"

        try:
            await send_password_reset_email(to=user.email, reset_url=reset_url)
        except Exception:
            logger.exception("Failed to send password reset email to %s", user.email)

    return ForgotPasswordResponse()


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
)
async def reset_password(
    payload: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
) -> ResetPasswordResponse:
    """Сброс пароля по токену из письма."""
    if len(payload.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль должен быть не менее 6 символов",
        )

    token_hash = _hash_reset_token(payload.token)

    record = await session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка недействительна или устарела",
        )

    if record.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка уже использована",
        )

    now = datetime.now(UTC)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка истекла. Запросите новую.",
        )

    user = await session.scalar(select(User).where(User.id == record.user_id))
    if user is None or user.deleted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Аккаунт недоступен",
        )

    user.hashed_password = hash_password(payload.new_password)
    record.used_at = now
    await session.commit()

    try:
        await send_password_changed_email(to=user.email)
    except Exception:
        logger.exception("Failed to send password changed email to %s", user.email)

    return ResetPasswordResponse()


# ============================================================
# Email Verification (double opt-in)
# ============================================================


def _hash_email_token(token: str) -> str:
    """SHA-256 хеш токена подтверждения email."""
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


async def _create_email_verification_token(
    session: AsyncSession,
    user: User,
) -> str:
    """Создаёт токен подтверждения email и возвращает raw-токен."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_email_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    session.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await session.commit()
    return raw_token


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_email(
    payload: VerifyEmailRequest,
    session: AsyncSession = Depends(get_session),
) -> VerifyEmailResponse:
    """Подтверждение email по токену из письма."""
    token_hash = _hash_email_token(payload.token)

    record = await session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка недействительна или устарела",
        )

    if record.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка уже использована",
        )

    now = datetime.now(UTC)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка истекла. Запросите новую.",
        )

    user = await session.scalar(select(User).where(User.id == record.user_id))
    if user is None or user.deleted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Аккаунт недоступен",
        )

    user.email_verified = True
    record.used_at = now
    await session.commit()

    return VerifyEmailResponse()


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    status_code=status.HTTP_200_OK,
)
async def resend_verification(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResendVerificationResponse:
    """Повторная отправка письма для подтверждения email."""
    if current_user.email_verified:
        return ResendVerificationResponse(detail="Email уже подтверждён.")

    raw_token = await _create_email_verification_token(session, current_user)
    verify_url = f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={raw_token}"

    try:
        await send_email_verification_email(to=current_user.email, verify_url=verify_url)
    except Exception:
        logger.exception("Failed to send verification email to %s", current_user.email)

    return ResendVerificationResponse()
