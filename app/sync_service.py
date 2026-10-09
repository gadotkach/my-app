"""Сервис авто-синхронизации: проверяет устаревание last_sync_at и запускает sync в фоне."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_logger import set_log_context
from app.crypto import decrypt
from app.database import AsyncSessionLocal
from app.models import Marketplace, MarketplaceAccount
from app.scheduler import sync_ozon_for_account, sync_wb_for_account

logger = logging.getLogger(__name__)


# Пороги устаревания (в минутах)
STALE_THRESHOLDS = {
    "ozon": 15,  # Ozon: каждые 15 минут
    "wildberries_product": 60,  # WB products: 1 час (лимит Базового токена)
    "wildberries_sales": 1440,  # 24ч: Базовый токен WB Finance API — 1 запрос/24ч
}

# In-memory lock, чтобы не запускать один и тот же sync параллельно
_sync_in_progress: set[str] = set()


def _key(user_id: int, marketplace_code: str, kind: str) -> str:
    return f"{user_id}:{marketplace_code}:{kind}"


def _is_stale(last_sync: datetime | None, threshold_minutes: int) -> bool:
    """True, если last_sync старше threshold_minutes или отсутствует."""
    if last_sync is None:
        return True
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last_sync) > timedelta(minutes=threshold_minutes)


async def _update_last_sync(account_id: int) -> None:
    async with AsyncSessionLocal() as session:
        account = await session.scalar(
            select(MarketplaceAccount).where(MarketplaceAccount.id == account_id)
        )
        if account is not None:
            account.last_sync_at = datetime.now(UTC)
            await session.commit()


async def _run_ozon_sync(user_id: int, account_id: int) -> None:
    key = _key(user_id, "ozon", "all")
    if key in _sync_in_progress:
        logger.info("Ozon sync already in progress for user=%s", user_id)
        return
    _sync_in_progress.add(key)
    try:
        async with AsyncSessionLocal() as session:
            account = await session.scalar(
                select(MarketplaceAccount).where(MarketplaceAccount.id == account_id)
            )
            if account is None or account.client_id is None:
                return
            api_key = decrypt(account.api_key_encrypted)
            client_id = account.client_id
            marketplace_id = account.marketplace_id

        set_log_context(user_id=user_id, marketplace="ozon")
        stats = await sync_ozon_for_account(
            user_id=user_id,
            client_id=client_id,
            api_key=api_key,
            marketplace_id=marketplace_id,
        )
        logger.info("Auto-sync Ozon user=%s: %s", user_id, stats)
        await _update_last_sync(account_id)
    except Exception:
        logger.exception("Auto-sync Ozon failed for user=%s", user_id)
    finally:
        _sync_in_progress.discard(key)


async def _run_wb_sync(user_id: int, account_id: int, kind: str) -> None:
    """
    WB sync в scheduler делает и products, и sales сразу.
    Пороги разные, но синк — один. Запускаем, если хотя бы один порог сработал.
    """
    key = _key(user_id, "wildberries", kind)
    if key in _sync_in_progress:
        logger.info("WB %s sync already in progress for user=%s", kind, user_id)
        return
    _sync_in_progress.add(key)
    try:
        async with AsyncSessionLocal() as session:
            account = await session.scalar(
                select(MarketplaceAccount).where(MarketplaceAccount.id == account_id)
            )
            if account is None:
                return
            api_key = decrypt(account.api_key_encrypted)
            marketplace_id = account.marketplace_id

        set_log_context(user_id=user_id, marketplace="wildberries")
        stats = await sync_wb_for_account(
            user_id=user_id,
            api_key=api_key,
            marketplace_id=marketplace_id,
        )
        logger.info("Auto-sync WB (%s) user=%s: %s", kind, user_id, stats)
        await _update_last_sync(account_id)
    except Exception:
        logger.exception("Auto-sync WB %s failed for user=%s", kind, user_id)
    finally:
        _sync_in_progress.discard(key)


async def trigger_sync_if_stale(user_id: int, session: AsyncSession) -> dict[str, list[str]]:
    """
    Проверяет все аккаунты пользователя.
    Для устаревших — запускает фоновый sync (без блокировки HTTP-запроса).
    """
    stmt = (
        select(MarketplaceAccount, Marketplace.code)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(MarketplaceAccount.user_id == user_id)
    )
    rows = (await session.execute(stmt)).all()

    triggered: list[str] = []
    skipped: list[str] = []

    for account, marketplace_code in rows:
        if marketplace_code == "ozon":
            if _is_stale(account.last_sync_at, STALE_THRESHOLDS["ozon"]):
                asyncio.create_task(_run_ozon_sync(user_id, account.id))
                triggered.append("ozon")
            else:
                skipped.append("ozon")

        elif marketplace_code == "wildberries":
            wb_triggered = False
            if _is_stale(account.last_sync_at, STALE_THRESHOLDS["wildberries_product"]):
                wb_triggered = True
                triggered.append("wb_products")
            else:
                skipped.append("wb_products")

            if _is_stale(account.last_sync_at, STALE_THRESHOLDS["wildberries_sales"]):
                if not wb_triggered:
                    triggered.append("wb_sales")
                wb_triggered = True
            else:
                skipped.append("wb_sales")

            if wb_triggered:
                asyncio.create_task(_run_wb_sync(user_id, account.id, "all"))

    return {"triggered": triggered, "skipped": skipped}
