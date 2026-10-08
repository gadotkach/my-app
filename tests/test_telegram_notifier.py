"""Unit-тесты сервиса telegram_notifier."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.telegram_notifier import (
    TelegramNotifierError,
    send_message,
)


@pytest.mark.asyncio
async def test_send_message_no_token(monkeypatch):
    """Без TELEGRAM_BOT_TOKEN → ошибка."""
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "")

    with pytest.raises(TelegramNotifierError, match="не настроен"):
        await send_message("123456789", "test")


@pytest.mark.asyncio
async def test_send_message_success(monkeypatch):
    """Успешная отправка через httpx."""
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "TEST_TOKEN")
    monkeypatch.setattr(settings, "telegram_proxy_url", "")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
    mock_response.text = '{"ok": true}'

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.services.telegram_notifier.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await send_message("123456789", "test message")

    assert result["ok"] is True
    # Проверяем URL — должен быть api.telegram.org
    call_args = mock_client.post.call_args
    assert "api.telegram.org" in call_args[0][0]
    assert "TEST_TOKEN" in call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_uses_proxy(monkeypatch):
    """С telegram_proxy_url — URL идёт на Cloudflare Worker."""
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "TEST_TOKEN")
    monkeypatch.setattr(
        settings,
        "telegram_proxy_url",
        "https://tg-proxy-agregators.shvaboe.workers.dev",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {}}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.services.telegram_notifier.httpx.AsyncClient",
        return_value=mock_client,
    ):
        await send_message("123456789", "test")

    call_args = mock_client.post.call_args
    assert "tg-proxy-agregators.shvaboe.workers.dev" in call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_http_error(monkeypatch):
    """HTTP 401 → TelegramNotifierError."""
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "TEST_TOKEN")
    monkeypatch.setattr(settings, "telegram_proxy_url", "")

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.services.telegram_notifier.httpx.AsyncClient",
        return_value=mock_client,
    ):
        with pytest.raises(TelegramNotifierError, match="401"):
            await send_message("123456789", "test")
