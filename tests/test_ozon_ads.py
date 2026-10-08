"""Тесты эндпоинтов /integrations/ozon-ads/*."""

from datetime import date
from typing import Any


async def _register_and_login(client, email: str = "ozon-ads@example.com") -> str:
    await client.post(
        "/auth/register",
        json={"email": email, "name": "Seller", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": email, "name": "x", "password": "secret123"},
    )
    return login.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# POST /integrations/ozon-ads/connect
# ============================================================


async def test_ozon_ads_connect_requires_auth(client):
    """Без токена → 401."""
    response = await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "test-client", "client_secret": "secret"},
    )
    assert response.status_code == 401


async def test_ozon_ads_connect_invalid_credentials(client, monkeypatch):
    """verify_credentials → False → 400."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return False

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )

    response = await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "bad-client", "client_secret": "bad-secret"},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert "Ozon Ads" in response.json()["detail"]


async def test_ozon_ads_connect_success(client, monkeypatch):
    """verify_credentials → True → 201, client_id сохранён."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return True

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )

    response = await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "106448101@test", "client_secret": "secret-abc"},
        headers=_auth(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "106448101@test"
    assert data["last_sync_at"] is None
    assert data["id"] > 0


async def test_ozon_ads_connect_updates_existing(client, monkeypatch):
    """Повторный connect — обновляет credentials, не создаёт новый."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return True

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )

    # Первый connect
    r1 = await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "client-1", "client_secret": "secret-1"},
        headers=_auth(token),
    )
    assert r1.status_code == 201
    first_id = r1.json()["id"]

    # Второй connect — тот же user_id
    r2 = await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "client-2", "client_secret": "secret-2"},
        headers=_auth(token),
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == first_id
    assert r2.json()["client_id"] == "client-2"


# ============================================================
# GET /integrations/ozon-ads/account
# ============================================================


async def test_ozon_ads_get_account_not_connected(client):
    """Не подключён → 404."""
    token = await _register_and_login(client)

    response = await client.get(
        "/integrations/ozon-ads/account",
        headers=_auth(token),
    )
    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "not connected" in detail


async def test_ozon_ads_get_account_success(client, monkeypatch):
    """Подключён → 200 с client_id."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return True

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )

    await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "my-client", "client_secret": "my-secret"},
        headers=_auth(token),
    )

    response = await client.get(
        "/integrations/ozon-ads/account",
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["client_id"] == "my-client"


# ============================================================
# DELETE /integrations/ozon-ads/account
# ============================================================


async def test_ozon_ads_disconnect(client, monkeypatch):
    """Disconnect → 204, потом 404 на GET."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return True

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )

    await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "del-client", "client_secret": "del-secret"},
        headers=_auth(token),
    )

    r = await client.delete(
        "/integrations/ozon-ads/account",
        headers=_auth(token),
    )
    assert r.status_code == 204

    r2 = await client.get(
        "/integrations/ozon-ads/account",
        headers=_auth(token),
    )
    assert r2.status_code == 404


# ============================================================
# POST /integrations/ozon-ads/sync
# ============================================================


async def test_ozon_ads_sync_not_connected(client):
    """Sync без connect → 404."""
    token = await _register_and_login(client)

    response = await client.post(
        "/integrations/ozon-ads/sync?from=2026-10-01&to=2026-10-07",
        headers=_auth(token),
    )
    assert response.status_code == 404


async def test_ozon_ads_sync_no_campaigns(client, monkeypatch):
    """Sync, но нет кампаний → skipped=True, created=0."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return True

    async def fake_sync(
        user_id: int,
        client_id: str,
        client_secret: str,
        date_from: date,
        date_to: date,
    ) -> dict[str, Any]:
        return {
            "created": 0,
            "updated": 0,
            "period_from": date_from,
            "period_to": date_to,
            "skipped": True,
        }

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )
    monkeypatch.setattr(
        "app.routers.ozon_ads.sync_ozon_ads",
        fake_sync,
    )

    await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "sync-client", "client_secret": "sync-secret"},
        headers=_auth(token),
    )

    response = await client.post(
        "/integrations/ozon-ads/sync?from=2026-10-01&to=2026-10-07",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 0
    assert data["skipped"] is True
    assert data["period_from"] == "2026-10-01"
    assert data["period_to"] == "2026-10-07"


async def test_ozon_ads_sync_creates_expenses(client, monkeypatch):
    """Sync → создаёт расходы (мокаем sync_ozon_ads)."""
    token = await _register_and_login(client)

    async def fake_verify(self) -> bool:
        return True

    async def fake_sync(
        user_id: int,
        client_id: str,
        client_secret: str,
        date_from: date,
        date_to: date,
    ) -> dict[str, Any]:
        return {
            "created": 3,
            "updated": 0,
            "period_from": date_from,
            "period_to": date_to,
            "skipped": False,
        }

    monkeypatch.setattr(
        "app.routers.ozon_ads.OzonAdsClient.verify_credentials",
        fake_verify,
    )
    monkeypatch.setattr(
        "app.routers.ozon_ads.sync_ozon_ads",
        fake_sync,
    )

    await client.post(
        "/integrations/ozon-ads/connect",
        json={"client_id": "sync-ok", "client_secret": "sync-ok"},
        headers=_auth(token),
    )

    response = await client.post(
        "/integrations/ozon-ads/sync?from=2026-10-01&to=2026-10-07",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 3
    assert data["skipped"] is False
