"""Тесты защиты от вечного trial через UsedMarketplaceIdentity.

Сценарий: два юзера, один магазин (client_id / api_key) → второй теряет trial.

⚠️ Важно: /auth/register использует TrialIdentity (IP+UA) и в тестах
оба юзера получают один и тот же identity_hash → второй автоматически "none".
Чтобы проверить именно защиту через UsedMarketplaceIdentity, принудительно
ставим второму юзеру "trialing" (см. _force_trialing).
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text


async def _force_trialing(engine, email: str) -> None:
    """Обход TrialIdentity: принудительно ставим trialing для email."""
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET subscription_status = 'trialing' WHERE email = :email"),
            {"email": email},
        )


async def _connect_ozon(client, headers, client_id: str, api_key: str = "test_api_key"):
    """Хелпер: подключить Ozon с моком OzonClient."""
    with patch("app.routers.integrations.OzonClient") as mock_cls:
        mock_instance = mock_cls.return_value.__aenter__.return_value
        mock_instance.get_seller_info = AsyncMock(return_value={"company": {}})
        response = await client.post(
            "/integrations/ozon/connect",
            json={
                "marketplace_code": "ozon",
                "client_id": client_id,
                "api_key": api_key,
            },
            headers=headers,
        )
    return response


async def _connect_wb(client, headers, api_key: str):
    """Хелпер: подключить WB с моком WBClient."""
    with patch("app.routers.integrations.WBClient") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.ping = AsyncMock(return_value=True)
        response = await client.post(
            "/integrations/wb/connect",
            json={
                "marketplace_code": "wildberries",
                "api_key": api_key,
            },
            headers=headers,
        )
    return response


# ============================================================
# Ozon
# ============================================================


@pytest.mark.asyncio
async def test_first_user_keeps_trial(client, auth_headers):
    """Первый юзер подключает Ozon — trial сохраняется."""
    r = await _connect_ozon(client, auth_headers, "CLIENT_FIRST")
    assert r.status_code in (200, 201), r.text

    me = await client.get("/users/me", headers=auth_headers)
    assert me.json()["subscription_status"] == "trialing"


@pytest.mark.asyncio
async def test_second_user_same_client_loses_trial(
    client, auth_headers, second_user_headers, engine
):
    """Второй юзер с тем же client_id → trial отменяется."""
    # Юзер A
    r1 = await _connect_ozon(client, auth_headers, "CLIENT_SHARED")
    assert r1.status_code in (200, 201)

    # Обход TrialIdentity: B получает "none" из-за /auth/register
    await _force_trialing(engine, "second@example.com")

    # Юзер B — тот же client_id
    r2 = await _connect_ozon(client, second_user_headers, "CLIENT_SHARED", api_key="different_key")
    assert r2.status_code in (200, 201), r2.text

    # У B trial отменён
    me_b = await client.get("/users/me", headers=second_user_headers)
    assert me_b.json()["subscription_status"] == "none"

    # У A trial сохранён
    me_a = await client.get("/users/me", headers=auth_headers)
    assert me_a.json()["subscription_status"] == "trialing"


@pytest.mark.asyncio
async def test_same_user_reconnect_keeps_trial(client, auth_headers):
    """Тот же юзер повторно подключает тот же client_id — trial сохраняется."""
    await _connect_ozon(client, auth_headers, "CLIENT_SELF")
    await _connect_ozon(client, auth_headers, "CLIENT_SELF")

    me = await client.get("/users/me", headers=auth_headers)
    assert me.json()["subscription_status"] == "trialing"


@pytest.mark.asyncio
async def test_different_client_ids_keep_trial(client, auth_headers, second_user_headers, engine):
    """Разные client_id у двух юзеров — оба сохраняют trial."""
    await _connect_ozon(client, auth_headers, "CLIENT_A")

    # Обход TrialIdentity для B
    await _force_trialing(engine, "second@example.com")

    await _connect_ozon(client, second_user_headers, "CLIENT_B")

    me_a = await client.get("/users/me", headers=auth_headers)
    me_b = await client.get("/users/me", headers=second_user_headers)
    assert me_a.json()["subscription_status"] == "trialing"
    assert me_b.json()["subscription_status"] == "trialing"


# ============================================================
# WB
# ============================================================


@pytest.mark.asyncio
async def test_wb_second_user_same_api_key_loses_trial(
    client, auth_headers, second_user_headers, engine
):
    """WB: второй юзер с тем же api_key — trial отменяется."""
    SHARED_KEY = "wb_shared_api_key_12345"

    r1 = await _connect_wb(client, auth_headers, SHARED_KEY)
    assert r1.status_code in (200, 201), r1.text

    # Обход TrialIdentity для B
    await _force_trialing(engine, "second@example.com")

    r2 = await _connect_wb(client, second_user_headers, SHARED_KEY)
    assert r2.status_code in (200, 201), r2.text

    me_b = await client.get("/users/me", headers=second_user_headers)
    assert me_b.json()["subscription_status"] == "none"


@pytest.mark.asyncio
async def test_ozon_wb_dont_cross_identity(client, auth_headers, second_user_headers, engine):
    """client_id из Ozon и api_key из WB не пересекаются (разный code в хеше)."""
    SAME = "identical_string_xyz"

    # Юзер A: Ozon с client_id=SAME
    r1 = await _connect_ozon(client, auth_headers, SAME)
    assert r1.status_code in (200, 201)

    # Обход TrialIdentity для B
    await _force_trialing(engine, "second@example.com")

    # Юзер B: WB с api_key=SAME — не должен пересечься
    r2 = await _connect_wb(client, second_user_headers, SAME)
    assert r2.status_code in (200, 201), r2.text

    me_b = await client.get("/users/me", headers=second_user_headers)
    assert me_b.json()["subscription_status"] == "trialing"
