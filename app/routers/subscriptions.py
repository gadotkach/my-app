from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.deps import get_current_user, get_session
from app.models import Payment, User
from app.yookassa_client import create_subscription_payment

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/create")
async def create_subscription(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Создаёт платёж в ЮKassa для оформления подписки."""
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider is not configured",
        )

    amount = Decimal(settings.subscription_price_rub)

    try:
        result = await run_in_threadpool(
            create_subscription_payment,
            current_user.id,
            current_user.email,
            amount,
            f"Подписка на 30 дней ({current_user.email})",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Payment provider error: {e}",
        ) from e

    return {
        "payment_id": result["payment_id"],
        "confirmation_url": result["confirmation_url"],
        "amount": settings.subscription_price_rub,
        "currency": "RUB",
    }


@router.post("/webhook")
async def yookassa_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Обрабатывает уведомления от ЮKassa.

    ЮKassa присылает событие payment.succeeded, когда платёж успешен.
    Мы находим юзера по metadata.user_id, активируем подписку, сохраняем Payment.
    """
    payload = await request.json()

    event = payload.get("event")
    obj = payload.get("object", {})

    if event != "payment.succeeded":
        return {"status": "ignored"}

    payment_id = obj.get("id")
    amount = obj.get("amount", {}).get("value")
    metadata = obj.get("metadata", {})
    user_id = metadata.get("user_id")

    if not user_id or not payment_id:
        return {"status": "missing metadata"}

    user = await session.get(User, int(user_id))
    if user is None:
        return {"status": "user not found"}

    now = datetime.now(UTC)
    period_days = settings.subscription_period_days

    user.subscription_status = "active"
    user.subscription_ends_at = now + timedelta(days=period_days)

    existing = await session.scalar(select(Payment).where(Payment.external_id == payment_id))
    if existing is None:
        session.add(
            Payment(
                user_id=user.id,
                provider="yookassa",
                external_id=payment_id,
                amount=amount,
                currency="RUB",
                status="succeeded",
                description=f"Подписка на {period_days} дней",
                paid_at=now,
            )
        )

    await session.commit()

    return {"status": "ok"}
