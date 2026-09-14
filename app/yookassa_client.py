"""Клиент ЮKassa. Обёртка над официальным SDK."""

import json
import uuid
from decimal import Decimal
from typing import Any

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
) -> dict[str, Any]:
    """Создаёт платёж в ЮKassa. Возвращает dict с confirmation_url и payment_id."""
    _configure()

    idempotence_key = str(uuid.uuid4())

    request_body = {
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
            "user_id": str(user_id),
            "email": email,
        },
    }

    print("=== YOOKASSA REQUEST ===")
    print(json.dumps(request_body, indent=2, ensure_ascii=False))
    print("========================")

    payment = Payment.create(request_body, idempotence_key)

    print("=== YOOKASSA PAYMENT ===")
    print("id:", payment.id)
    print("status:", payment.status)
    print("confirmation:", payment.confirmation)
    print("========================")

    confirmation_url = None
    if payment.confirmation is not None:
        confirmation_url = payment.confirmation.confirmation_url

    return {
        "payment_id": payment.id,
        "confirmation_url": confirmation_url,
        "status": payment.status,
    }
