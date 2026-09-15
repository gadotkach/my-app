"""Тесты эндпоинта /analytics/profit."""


async def _register_and_login(client, email: str = "profit@example.com") -> str:
    await client.post(
        "/auth/register",
        json={"email": email, "name": "Seller", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": email, "name": "x", "password": "secret123"},
    )
    return login.json()["access_token"]


async def _create_product(
    client,
    token: str,
    sku: str = "SKU-1",
    name: str = "Товар",
    cost_price: str | None = "500.00",
) -> int:
    payload: dict[str, object] = {"sku": sku, "name": name}
    if cost_price is not None:
        payload["cost_price"] = cost_price
    response = await client.post(
        "/products",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_sale(
    client,
    token: str,
    product_id: int,
    marketplace_code: str = "ozon",
    external_id: str = "P-001",
    price: str = "1000.00",
    commission: str = "150.00",
    logistics: str = "100.00",
    sold_at: str = "2026-09-15T10:00:00Z",
) -> None:
    response = await client.post(
        "/sales",
        json={
            "marketplace_code": marketplace_code,
            "product_id": product_id,
            "external_id": external_id,
            "quantity": 1,
            "price": price,
            "commission": commission,
            "logistics_cost": logistics,
            "sold_at": sold_at,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


# ============================================================
# Доступ и пустой период
# ============================================================


async def test_profit_requires_auth(client):
    """Без токена → 401."""
    response = await client.get(
        "/analytics/profit?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z"
    )
    assert response.status_code == 401


async def test_profit_empty(client):
    """Нет продаж → нули, by_marketplace пустой."""
    token = await _register_and_login(client)
    response = await client.get(
        "/analytics/profit?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_revenue"] == "0"
    assert data["total_net_profit"] == "0"
    assert data["margin_percent"] == "0"
    assert data["by_marketplace"] == []


# ============================================================
# Одна площадка
# ============================================================


async def test_profit_single_marketplace(client):
    """3 продажи на Ozon → правильная агрегация."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")

    for i, price in enumerate(["1000.00", "1500.00", "2000.00"]):
        await _create_sale(
            client,
            token,
            product_id=product_id,
            external_id=f"O-{i}",
            price=price,
        )

    response = await client.get(
        "/analytics/profit?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # revenue = 1000 + 1500 + 2000 = 4500
    assert data["total_revenue"] == "4500.00"
    # costs = 250 × 3 = 750
    assert data["total_marketplace_costs"] == "750.00"
    # cogs = 500 × 3 = 1500
    assert data["total_cogs"] == "1500.00"
    # net_profit = 4500 − 750 − 1500 = 2250
    assert data["total_net_profit"] == "2250.00"
    # margin = 2250 / 4500 × 100 = 50.00
    assert data["margin_percent"] == "50.00"

    assert len(data["by_marketplace"]) == 1
    mp = data["by_marketplace"][0]
    assert mp["marketplace_code"] == "ozon"
    assert mp["sales_count"] == 3
    assert mp["revenue"] == "4500.00"
    assert mp["net_profit"] == "2250.00"


# ============================================================
# Несколько площадок
# ============================================================


async def test_profit_multiple_marketplaces(client):
    """Ozon + WB → правильная группировка и сортировка по прибыли."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")

    # Ozon: 2 продажи по 2000
    await _create_sale(
        client, token, product_id=product_id, marketplace_code="ozon",
        external_id="O-1", price="2000.00",
    )
    await _create_sale(
        client, token, product_id=product_id, marketplace_code="ozon",
        external_id="O-2", price="2000.00",
    )
    # WB: 1 продажа 1000
    await _create_sale(
        client, token, product_id=product_id, marketplace_code="wildberries",
        external_id="W-1", price="1000.00",
    )

    response = await client.get(
        "/analytics/profit?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total_revenue"] == "5000.00"
    assert len(data["by_marketplace"]) == 2

    # Сортировка по net_profit по убыванию — Ozon первый
    assert data["by_marketplace"][0]["marketplace_code"] == "ozon"
    assert data["by_marketplace"][0]["sales_count"] == 2
    assert data["by_marketplace"][1]["marketplace_code"] == "wildberries"
    assert data["by_marketplace"][1]["sales_count"] == 1


# ============================================================
# Себестоимость и налоги
# ============================================================


async def test_profit_without_cost_price(client):
    """Себестоимость не задана → cogs = 0, прибыль выше."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price=None)

    await _create_sale(client, token, product_id=product_id, price="1000.00")

    response = await client.get(
        "/analytics/profit?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total_cogs"] == "0.00"
    # revenue = 1000, costs = 250, cogs = 0 → net_profit = 750
    assert data["total_net_profit"] == "750.00"


async def test_profit_with_tax_settings(client):
    """С УСН Доходы 6% → правильный налог."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")
    await _create_sale(client, token, product_id=product_id, price="1000.00")

    # Настройки налога
    await client.put(
        "/tax-settings",
        json={
            "tax_system": "USN_INCOME",
            "tax_rate": "6.00",
            "insurance_contributions": "0.00",
            "vat_enabled": False,
            "vat_rate": "0.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get(
        "/analytics/profit?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # revenue = 1000, tax = 60, gross_profit = 250, net_profit = 190
    assert data["total_tax"] == "60.00"
    assert data["total_net_profit"] == "190.00"


# ============================================================
# Фильтр по дате
# ============================================================


async def test_profit_filters_by_date(client):
    """Продажи вне периода не учитываются."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")

    # Сентябрь
    await _create_sale(
        client, token, product_id=product_id,
        external_id="SEP", sold_at="2026-09-15T10:00:00Z",
    )
    # Октябрь
    await _create_sale(
        client, token, product_id=product_id,
        external_id="OCT", sold_at="2026-10-15T10:00:00Z",
    )

    # Только сентябрь
    response = await client.get(
        "/analytics/profit?from=2026-09-01T00:00:00Z&to=2026-09-30T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Учтена только одна продажа
    assert data["by_marketplace"][0]["sales_count"] == 1
    assert data["total_revenue"] == "1000.00"
