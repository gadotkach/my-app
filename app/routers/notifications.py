"""Эндпоинты для Telegram-уведомлений."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, require_active_subscription
from app.models import TelegramSubscription, User
from app.schemas import (
    TelegramConnect,
    TelegramSettingsUpdate,
    TelegramSubscriptionRead,
    TelegramTestResult,
)
from app.services.telegram_notifier import (
    TelegramNotifierError,
    notify_test,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications/telegram", tags=["notifications"])


@router.post(
    "/connect",
    response_model=TelegramSubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_telegram(
    payload: TelegramConnect,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> TelegramSubscription:
    """Подключить Telegram: сохранить chat_id."""
    existing = await session.scalar(
        select(TelegramSubscription).where(TelegramSubscription.user_id == current_user.id)
    )
    if existing is not None:
        existing.chat_id = payload.chat_id
        existing.telegram_username = payload.telegram_username
        await session.commit()
        await session.refresh(existing)
        return existing

    sub = TelegramSubscription(
        user_id=current_user.id,
        chat_id=payload.chat_id,
        telegram_username=payload.telegram_username,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


@router.get("/subscription", response_model=TelegramSubscriptionRead)
async def get_subscription(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> TelegramSubscription:
    """Получить подписку."""
    sub = await session.scalar(
        select(TelegramSubscription).where(TelegramSubscription.user_id == current_user.id)
    )
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram subscription is not connected",
        )
    return sub


@router.delete("/subscription", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_telegram(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Отключить Telegram."""
    sub = await session.scalar(
        select(TelegramSubscription).where(TelegramSubscription.user_id == current_user.id)
    )
    if sub is not None:
        await session.delete(sub)
        await session.commit()


@router.patch("/subscription", response_model=TelegramSubscriptionRead)
async def update_settings(
    payload: TelegramSettingsUpdate,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> TelegramSubscription:
    """Обновить настройки уведомлений."""
    sub = await session.scalar(
        select(TelegramSubscription).where(TelegramSubscription.user_id == current_user.id)
    )
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram subscription is not connected",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(sub, field, value)
    await session.commit()
    await session.refresh(sub)
    return sub


@router.post("/test", response_model=TelegramTestResult)
async def send_test(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> TelegramTestResult:
    """Отправить тестовое сообщение."""
    sub = await session.scalar(
        select(TelegramSubscription).where(TelegramSubscription.user_id == current_user.id)
    )
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram subscription is not connected",
        )

    try:
        await notify_test(sub.chat_id)
    except TelegramNotifierError as e:
        return TelegramTestResult(sent=False, detail=str(e))

    sub.last_notification_at = datetime.now(UTC)
    await session.commit()
    return TelegramTestResult(sent=True, detail=None)
