"""Тесты эндпоинтов /notifications/telegram/*."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.telegram_notifier import TelegramNotifierError

# ============================================================
# POST /notifications/telegram/connect
# ============================================================


@pytest.mark.asyncio
async def test_connect_requires_auth(client):
    """Без токена → 401."""
    response = await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "123456789"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_connect_success(client, auth_headers):
    """Успешное подключение → 201."""
    response = await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "380946555", "telegram_username": "gadotkach"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["chat_id"] == "380946555"
    assert data["telegram_username"] == "gadotkach"
    assert data["notify_new_sales"] is True
    assert data["notify_loss_making"] is True
    assert data["notify_daily_report"] is False
    assert data["notify_drr_high"] is True
    assert data["last_notification_at"] is None


@pytest.mark.asyncio
async def test_connect_updates_existing(client, auth_headers):
    """Повторный connect — обновляет, не создаёт новый."""
    r1 = await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "111111", "telegram_username": "user1"},
        headers=auth_headers,
    )
    assert r1.status_code == 201
    first_id = r1.json()["id"]

    r2 = await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "222222", "telegram_username": "user2"},
        headers=auth_headers,
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == first_id
    assert r2.json()["chat_id"] == "222222"
    assert r2.json()["telegram_username"] == "user2"


# ============================================================
# GET /notifications/telegram/subscription
# ============================================================


@pytest.mark.asyncio
async def test_get_subscription_not_connected(client, auth_headers):
    """Нет подписки → 404."""
    response = await client.get(
        "/notifications/telegram/subscription",
        headers=auth_headers,
    )
    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "not connected" in detail


@pytest.mark.asyncio
async def test_get_subscription_success(client, auth_headers):
    """200 + JSON, если подключён."""
    await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "333333"},
        headers=auth_headers,
    )
    response = await client.get(
        "/notifications/telegram/subscription",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["chat_id"] == "333333"


# ============================================================
# PATCH /notifications/telegram/subscription
# ============================================================


@pytest.mark.asyncio
async def test_update_settings(client, auth_headers):
    """PATCH сохраняет настройки."""
    await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "444444"},
        headers=auth_headers,
    )

    response = await client.patch(
        "/notifications/telegram/subscription",
        json={
            "notify_daily_report": True,
            "drr_threshold": "60.00",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["notify_daily_report"] is True
    assert data["drr_threshold"] == "60.00"
    # Не изменённые поля остались
    assert data["notify_new_sales"] is True


@pytest.mark.asyncio
async def test_update_settings_not_connected(client, auth_headers):
    """PATCH без подписки → 404."""
    response = await client.patch(
        "/notifications/telegram/subscription",
        json={"notify_daily_report": True},
        headers=auth_headers,
    )
    assert response.status_code == 404


# ============================================================
# DELETE /notifications/telegram/subscription
# ============================================================


@pytest.mark.asyncio
async def test_disconnect(client, auth_headers):
    """DELETE → 204, потом GET → 404."""
    await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "555555"},
        headers=auth_headers,
    )

    r = await client.delete(
        "/notifications/telegram/subscription",
        headers=auth_headers,
    )
    assert r.status_code == 204

    r2 = await client.get(
        "/notifications/telegram/subscription",
        headers=auth_headers,
    )
    assert r2.status_code == 404


# ============================================================
# POST /notifications/telegram/test
# ============================================================


@pytest.mark.asyncio
async def test_send_test_success(client, auth_headers):
    """Успешная отправка тестового сообщения."""
    await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "666666"},
        headers=auth_headers,
    )

    with patch(
        "app.routers.notifications.notify_test",
        new=AsyncMock(return_value=None),
    ):
        response = await client.post(
            "/notifications/telegram/test",
            headers=auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert data["sent"] is True
    assert data["detail"] is None


@pytest.mark.asyncio
async def test_send_test_failure(client, auth_headers):
    """Ошибка отправки → sent=False + detail."""
    await client.post(
        "/notifications/telegram/connect",
        json={"chat_id": "777777"},
        headers=auth_headers,
    )

    async def fake_notify_test(chat_id: str) -> None:
        raise TelegramNotifierError("Telegram API 401: Unauthorized")

    with patch(
        "app.routers.notifications.notify_test",
        new=fake_notify_test,
    ):
        response = await client.post(
            "/notifications/telegram/test",
            headers=auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert data["sent"] is False
    assert "401" in data["detail"]


@pytest.mark.asyncio
async def test_send_test_not_connected(client, auth_headers):
    """Тест без подписки → 404."""
    response = await client.post(
        "/notifications/telegram/test",
        headers=auth_headers,
    )
    assert response.status_code == 404
