"""Клиент ЮKassa. Обёртка над официальным SDK."""

from decimal import Decimal

from yookassa import Configuration, Payment

from app.config import settings


def _configure() -> None:
    Configuration.account_id = settings.yookassa_shop_id
    Configuration.secret_key = settings.yookassa_secret_key


def create_subscription_payment(
    user_id: int,
    email: str,
    amount_rub: Decimal,
    description: str,
) -> dict:
    """Создаёт платёж в ЮKassa. Возвращает dict с confirmation_url и payment_id."""
    _configure()

    idempotence_key = f"user-{user_id}-sub-{amount_rub}"

    payment = Payment.create(
        {
            "amount": {
                "value": str(amount_rub),
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": settings.yookassa_return_url,
            },
            "capture": True,
            "description": description,
            "metadata": {
                "user_id": user_id,
                "email": email,
            },
        },
        idempotence_key,
    )

    return {
        "payment_id": payment.id,
        "confirmation_url": payment.confirmation.confirmation_url,
        "status": payment.status,
    }
