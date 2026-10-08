"""Сервис отправки Telegram-уведомлений через Bot API."""

import logging
from typing import Any, cast

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifierError(Exception):
    """Ошибка отправки через Telegram Bot API."""


async def send_message(chat_id: str, text: str) -> dict[str, Any]:
    """Отправить сообщение в Telegram.

    Использует TELEGRAM_BOT_TOKEN из config.
    """
    if not settings.telegram_bot_token:
        raise TelegramNotifierError("TELEGRAM_BOT_TOKEN не настроен")

    url = f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload)

    if response.status_code >= 400:
        raise TelegramNotifierError(f"Telegram API {response.status_code}: {response.text[:200]}")

    data = response.json()
    if not data.get("ok"):
        raise TelegramNotifierError(f"Telegram API error: {data}")
    return cast(dict[str, Any], data)


async def notify_test(chat_id: str) -> None:
    """Тестовое сообщение."""
    await send_message(
        chat_id,
        "\u2705 <b>Agregators Notify</b>\n\n"
        "Уведомления успешно подключены!\n"
        "Вы будете получать информацию о заказах, убыточных товарах и высоком ДРР.",
    )


async def notify_loss_making(chat_id: str, product_name: str, loss: float) -> None:
    """Товар стал убыточным."""
    await send_message(
        chat_id,
        f"\U0001f534 <b>Товар стал убыточным</b>\n\n"
        f"<b>{product_name}</b>\n"
        f"Убыток: {loss:.2f} \u20bd\n\n"
        f"Проверьте цену, комиссии или рекламу.",
    )


async def notify_drr_high(chat_id: str, product_name: str, drr: float) -> None:
    """ДРР превысил порог."""
    await send_message(
        chat_id,
        f"\u26a0\ufe0f <b>Высокий ДРР</b>\n\n"
        f"<b>{product_name}</b>\n"
        f"ДРР: {drr:.1f}%\n\n"
        f"Рекламные расходы съедают прибыль.",
    )


async def notify_daily_report(chat_id: str, summary: dict[str, Any]) -> None:
    """Ежедневный отчёт."""
    await send_message(
        chat_id,
        f"\U0001f4ca <b>Ежедневный отчёт</b>\n\n"
        f"Выручка: {summary.get('revenue', 0):.0f} \u20bd\n"
        f"Прибыль: {summary.get('profit', 0):.0f} \u20bd\n"
        f"ДРР: {summary.get('drr', 0):.1f}%\n"
        f"Заказов: {summary.get('orders', 0)}",
    )
