"""Тесты эндпоинтов /integrations/wb/*."""

from typing import Any


async def _register_and_login(client, email: str = "wb@example.com") -> str:
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
# POST /integrations/wb/connect
# ============================================================


async def test_wb_connect_requires_auth(client):
    """Без токена → 401."""
    response = await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "test-token"},
    )
    assert response.status_code == 401


async def test_wb_connect_invalid_token(client, monkeypatch):
    """WBClient.ping → False → 400."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return False

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)

    response = await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "invalid-token"},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert "WB" in response.json()["detail"]


async def test_wb_connect_success(client, monkeypatch):
    """WBClient.ping → True → 201, client_id=None."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)

    response = await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "valid-token"},
        headers=_auth(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["marketplace_code"] == "wildberries"
    assert data["client_id"] is None
    assert data["id"] is not None


async def test_wb_connect_updates_existing(client, monkeypatch):
    """Повторный connect обновляет запись, не создаёт дубль."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)

    # Первый connect
    r1 = await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token-1"},
        headers=_auth(token),
    )
    assert r1.status_code == 201
    first_id = r1.json()["id"]

    # Второй connect — должен обновить ту же запись
    r2 = await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token-2"},
        headers=_auth(token),
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == first_id  # тот же id


# ============================================================
# POST /integrations/wb/sync/products
# ============================================================


async def test_wb_sync_products_requires_auth(client):
    """Без токена → 401."""
    response = await client.post("/integrations/wb/sync/products")
    assert response.status_code == 401


async def test_wb_sync_products_not_connected(client):
    """WB не подключён → 404."""
    token = await _register_and_login(client)
    response = await client.post(
        "/integrations/wb/sync/products",
        headers=_auth(token),
    )
    assert response.status_code == 404
    assert "not connected" in response.json()["detail"]


async def test_wb_sync_products_empty(client, monkeypatch):
    """WB подключён, но карточек нет → synced=0, created=0."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    async def fake_list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)
    monkeypatch.setattr("app.routers.integrations.WBClient.list_products", fake_list_products)

    # Подключаем WB
    await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token"},
        headers=_auth(token),
    )

    # Синхронизируем — пусто
    response = await client.post(
        "/integrations/wb/sync/products",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 0
    assert data["created"] == 0
    assert data["updated"] == 0


async def test_wb_sync_products_creates(client, monkeypatch):
    """Мок list_products → 3 карточки → 3 Product."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    async def fake_list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "nmID": 111111,
                "title": "Товар WB 1",
                "description": "Описание 1",
                "dimensions": {"length": 20, "width": 15, "height": 10},
            },
            {
                "nmID": 222222,
                "title": "Товар WB 2",
                "description": None,
                "dimensions": {"length": 30, "width": 25, "height": 15},
            },
            {
                "nmID": 333333,
                "title": "Товар WB 3",
                "description": "Описание 3",
                "dimensions": {},
            },
        ]

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)
    monkeypatch.setattr("app.routers.integrations.WBClient.list_products", fake_list_products)

    await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token"},
        headers=_auth(token),
    )

    response = await client.post(
        "/integrations/wb/sync/products",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 3
    assert data["created"] == 3
    assert data["updated"] == 0

    # Проверяем, что товары создались
    products_response = await client.get("/products", headers=_auth(token))
    assert products_response.status_code == 200
    products = products_response.json()
    assert len(products) == 3
    skus = {p["sku"] for p in products}
    assert skus == {"111111", "222222", "333333"}

    # Проверяем габариты у первого
    p1 = next(p for p in products if p["sku"] == "111111")
    assert p1["name"] == "Товар WB 1"
    assert p1["length_cm"] == "20.00"
    assert p1["width_cm"] == "15.00"
    assert p1["height_cm"] == "10.00"


async def test_wb_sync_products_updates(client, monkeypatch):
    """Повторный sync обновляет существующие товары."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    async def fake_list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "nmID": 111111,
                "title": "Товар WB 1 (обновлён)",
                "description": "Новое описание",
                "dimensions": {"length": 21, "width": 16, "height": 11},
            },
        ]

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)
    monkeypatch.setattr("app.routers.integrations.WBClient.list_products", fake_list_products)

    await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token"},
        headers=_auth(token),
    )

    # Первый sync
    r1 = await client.post(
        "/integrations/wb/sync/products",
        headers=_auth(token),
    )
    assert r1.json()["created"] == 1

    # Второй sync — обновление
    r2 = await client.post(
        "/integrations/wb/sync/products",
        headers=_auth(token),
    )
    data = r2.json()
    assert data["created"] == 0
    assert data["updated"] == 1

    # Проверяем, что название обновилось
    products_response = await client.get("/products", headers=_auth(token))
    products = products_response.json()
    assert len(products) == 1
    assert products[0]["name"] == "Товар WB 1 (обновлён)"


# ============================================================
# POST /integrations/wb/sync/sales
# ============================================================


async def test_wb_sync_sales_requires_auth(client):
    """Без токена → 401."""
    response = await client.post(
        "/integrations/wb/sync/sales?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z"
    )
    assert response.status_code == 401


async def test_wb_sync_sales_not_connected(client):
    """WB не подключён → 404."""
    token = await _register_and_login(client)
    response = await client.post(
        "/integrations/wb/sync/sales?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers=_auth(token),
    )
    assert response.status_code == 404


async def test_wb_sync_sales_empty(client, monkeypatch):
    """WB подключён, отчёт пустой → synced=0."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    async def fake_sales_report(self, date_from, date_to) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)
    monkeypatch.setattr("app.routers.integrations.WBClient.list_sales_report", fake_sales_report)

    await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token"},
        headers=_auth(token),
    )

    response = await client.post(
        "/integrations/wb/sync/sales?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 0
    assert data["created"] == 0
    assert data["updated"] == 0


async def test_wb_sync_sales_creates(client, monkeypatch):
    """Мок отчёта → создаются Sale с правильными полями."""
    token = await _register_and_login(client)

    async def fake_ping(self) -> bool:
        return True

    async def fake_list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "nmID": 111111,
                "title": "Товар WB 1",
                "description": None,
                "dimensions": {},
            },
        ]

    async def fake_sales_report(self, date_from, date_to) -> list[dict[str, Any]]:
        return [
            {
                "srid": "unique-srid-1",
                "nm_id": 111111,
                "ppvz_for_pay": "850.00",
                "ppvz_sales_commission": "150.00",
                "acquiring_fee": "15.00",
                "delivery_rub": "91.00",
                "storage_fee": "5.00",
                "retail_price_withdisc_rub": "1200.00",
                "ppvz_spp_prc": "5.00",
                "ppvz_vw": 1,
                "sale_dt": "2026-09-15T10:00:00Z",
            },
            {
                "srid": "unique-srid-2",
                "nm_id": 111111,
                "ppvz_for_pay": "1700.00",
                "ppvz_sales_commission": "300.00",
                "acquiring_fee": "30.00",
                "delivery_rub": "91.00",
                "storage_fee": "0.00",
                "retail_price_withdisc_rub": "2000.00",
                "ppvz_spp_prc": "3.00",
                "ppvz_vw": 2,
                "sale_dt": "2026-09-16T10:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routers.integrations.WBClient.ping", fake_ping)
    monkeypatch.setattr("app.routers.integrations.WBClient.list_products", fake_list_products)
    monkeypatch.setattr("app.routers.integrations.WBClient.list_sales_report", fake_sales_report)

    # Подключаем WB и синхронизируем товары (для маппинга nm_id → Product)
    await client.post(
        "/integrations/wb/connect",
        json={"marketplace_code": "wb", "api_key": "token"},
        headers=_auth(token),
    )
    await client.post(
        "/integrations/wb/sync/products",
        headers=_auth(token),
    )

    # Синхронизируем продажи
    response = await client.post(
        "/integrations/wb/sync/sales?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 2
    assert data["created"] == 2
    assert data["updated"] == 0

    # Проверяем, что продажи создались
    sales_response = await client.get("/sales", headers=_auth(token))
    assert sales_response.status_code == 200
    sales = sales_response.json()
    assert len(sales) == 2

    # Проверяем первую продажу
    s1 = next(s for s in sales if s["external_id"] == "unique-srid-1")
    # price = 850 + 150 + 15 + 91 = 1106
    assert s1["price"] == "1106.00"
    assert s1["commission"] == "150.00"
    assert s1["logistics_cost"] == "91.00"
    assert s1["product_id"] is not None  # должен быть привязан к Product
