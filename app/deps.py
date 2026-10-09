from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception
    sub = decode_access_token(credentials.credentials)
    if sub is None:
        raise credentials_exception
    ...
    try:
        user_id = int(sub)
    except ValueError:
        raise credentials_exception from None
    user = await session.get(User, user_id)
    if user is None:
        raise credentials_exception

    # Обновляем last_activity_at раз в 5 минут (не на каждый запрос)
    now = datetime.now(UTC)
    last = user.last_activity_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last is None or (now - last) > timedelta(minutes=5):
        user.last_activity_at = now
        await session.commit()

    return user


async def require_active_subscription(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency: пропускает только пользователей с активной подпиской или trial.

    Возвращает 402 Payment Required, если подписка истекла или отсутствует.
    """
    if current_user.subscription_status in ("none", "expired"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription required. Please subscribe to access this feature.",
        )
    return current_user
