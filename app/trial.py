import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.email_client import send_trial_revoked_email
from app.models import UsedMarketplaceIdentity, User

logger = logging.getLogger(__name__)


def hash_identity(ip: str, user_agent: str) -> str:
    """Хеш от IP + User-Agent. Используется для одного trial на устройство/сеть."""
    raw = f"{ip}|{user_agent}".encode()
    return hashlib.sha256(raw).hexdigest()


def hash_email(email: str) -> str:
    """Хеш от email в нижнем регистре. Чтобы хранить, не раскрывая сам email."""
    return hashlib.sha256(email.lower().encode()).hexdigest()


def hash_marketplace_identity(marketplace_code: str, identity: str) -> str:
    """Хеш от (marketplace_code, client_id или api_key).

    Используется для UsedMarketplaceIdentity — защиты от вечного trial.
    marketplace_code включается в хеш, чтобы client_id "ozon" и "wb"
    не могли случайно совпасть.
    """
    raw = f"{marketplace_code}:{identity}".encode()
    return hashlib.sha256(raw).hexdigest()


async def record_marketplace_usage(
    session: AsyncSession,
    user: User,
    marketplace_code: str,
    identity: str,
) -> bool:
    """Записывает использование маркетплейса (защита от вечного trial).

    Args:
        session: AsyncSession (уже открытая в роутере).
        user: текущий пользователь.
        marketplace_code: "ozon", "wb", ...
        identity: client_id для Ozon, raw api_key для WB.

    Returns:
        True — магазин уже использовался другим юзером
               (trial отменён, если был trialing).
        False — новое использование или тот же юзер.

    Побочный эффект:
        Если trial пользователя активен и магазин уже использовался
        другим — переводит subscription_status в "none".
    """
    identity_hash = hash_marketplace_identity(marketplace_code, identity)

    existing = await session.scalar(
        select(UsedMarketplaceIdentity).where(
            UsedMarketplaceIdentity.identity_hash == identity_hash
        )
    )

    if existing is None:
        # Первое использование — записываем
        session.add(
            UsedMarketplaceIdentity(
                marketplace_code=marketplace_code,
                identity_hash=identity_hash,
                first_user_id=user.id,
            )
        )
        await session.commit()
        return False

    if existing.first_user_id == user.id:
        # Тот же юзер — всё ок
        return False

    # Магазин уже использовался другим юзером
    if user.subscription_status == "trialing":
        user.subscription_status = "none"
        user.trial_revoked_reason = "marketplace_already_used"
        await session.commit()

        # Уведомление (best-effort)
        try:
            await send_trial_revoked_email(to=user.email)
        except Exception:
            logger.exception("Failed to send trial revoked email to %s", user.email)

        return True

    return True
