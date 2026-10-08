from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_session
from app.models import RefreshToken, TrialIdentity, User
from app.schemas import LoginRequest, RefreshResponse, Token, UserCreate, UserRead
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
            detail="User with this email already exists",
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

    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Token:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
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
