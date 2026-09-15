"""Тесты эндпоинта /analytics/unit-economics."""

from datetime import datetime


async def _register_and_login(client, email: str = "ue@example.com") -> str:
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
    product_id: int | None = None,
    marketplace_code: str = "ozon",
    external_id: str = "A-001",
    price: str = "1000.00",
    commission: str = "150.00",
    logistics: str = "100.00",
    sold_at: str = "2026-09-15T10:00:00Z",
) -> None:
    payload: dict[str, object] = {
        "marketplace_code": marketplace_code,
        "external_id": external_id,
        "quantity": 1,
        "price": price,
        "commission": commission,
        "logistics_cost": logistics,
        "sold_at": sold_at,
    }
    if product_id is not None:
        payload["product_id"] = product_id
    response = await client.post(
        "/sales",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


# ============================================================
# Базовые проверки доступа
# ============================================================


async def test_unit_economics_requires_auth(client):
    """Без токена → 401."""
    response = await client.get(
        "/analytics/unit-economics?product_id=1&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z"
    )
    assert response.status_code == 401


async def test_unit_economics_unknown_product(client):
    """Несуществующий product_id → 404."""
    token = await _register_and_login(client)
    response = await client.get(
        "/analytics/unit-economics?product_id=9999&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


async def test_unit_economics_requires_active_subscription(client):
    """Без активной подписки → 402 (даже если товар существует)."""
    token_a = await _register_and_login(client, email="a@example.com")
    product_id = await _create_product(client, token_a, sku="A-1")

    # Второй пользователь с того же клиента (IP + UA) не получит trial
    token_b = await _register_and_login(client, email="b@example.com")
    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 402


# ============================================================
# Расчёты
# ============================================================


async def test_unit_economics_no_sales(client):
    """Товар есть, продаж нет — нули и warning."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token)

    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sales_count"] == 0
    assert data["quantity"] == 0
    assert data["net_profit"] == "0"
    assert data["warning"] == "За выбранный период продаж не найдено"


async def test_unit_economics_single_sale(client):
    """Одна продажа с себестоимостью — корректный расчёт."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")
    await _create_sale(
        client,
        token,
        product_id=product_id,
        price="1000.00",
        commission="150.00",
        logistics="100.00",
    )

    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["sales_count"] == 1
    assert data["quantity"] == 1
    assert data["gross_revenue"] == "1000.00"
    assert data["net_revenue"] == "1000.00"
    assert data["commission"] == "150.00"
    assert data["logistics"] == "100.00"
    # payout = 1000 − 250 = 750; cogs = 500; gross_profit = 250
    assert data["payout"] == "750.00"
    assert data["cogs"] == "500.00"
    assert data["gross_profit"] == "250.00"
    # нет налоговых настроек → налог 0
    assert data["tax_amount"] == "0.00"
    assert data["net_profit"] == "250.00"
    assert data["margin_percent"] == "25.00"
    assert data["profit_per_unit"] == "250.00"
    assert data["warning"] is None


async def test_unit_economics_multiple_sales(client):
    """Три продажи → правильная агрегация."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")

    for i, price in enumerate(["1000.00", "1500.00", "2000.00"]):
        await _create_sale(
            client,
            token,
            product_id=product_id,
            external_id=f"M-{i}",
            price=price,
            commission="150.00",
            logistics="100.00",
        )

    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["sales_count"] == 3
    assert data["quantity"] == 3
    assert data["gross_revenue"] == "4500.00"
    # commission: 150 × 3 = 450
    assert data["commission"] == "450.00"
    # logistics: 100 × 3 = 300
    assert data["logistics"] == "300.00"
    # cogs: 500 × 3 = 1500
    assert data["cogs"] == "1500.00"
    # payout: 4500 − 750 = 3750
    assert data["payout"] == "3750.00"
    # gross_profit: 3750 − 1500 = 2250
    assert data["gross_profit"] == "2250.00"
    # tax нет → net_profit = 2250
    assert data["net_profit"] == "2250.00"
    # profit_per_unit: 2250 / 3 = 750
    assert data["profit_per_unit"] == "750.00"


async def test_unit_economics_loss_making(client):
    """Убыточный товар → warning и отрицательный профит."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="1500.00")
    await _create_sale(
        client,
        token,
        product_id=product_id,
        price="1000.00",
        commission="150.00",
        logistics="100.00",
    )

    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # payout = 750; cogs = 1500; gross_profit = −750
    assert data["gross_profit"] == "-750.00"
    assert data["net_profit"] == "-750.00"
    assert data["warning"] == "Товар убыточен за выбранный период"


async def test_unit_economics_with_tax_settings(client):
    """С налоговыми настройками УСН Доходы 6% — правильный налог."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")
    await _create_sale(
        client,
        token,
        product_id=product_id,
        price="1000.00",
        commission="150.00",
        logistics="100.00",
    )

    # Создаём налоговые настройки
    tax_response = await client.put(
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
    assert tax_response.status_code == 200

    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # net_revenue = 1000; gross_profit = 250; tax = 1000 × 6% = 60
    # net_profit = 250 − 60 = 190
    assert data["tax_amount"] == "60.00"
    assert data["net_profit"] == "190.00"
    assert data["margin_percent"] == "19.00"


async def test_unit_economics_filters_by_date(client):
    """Продажи вне периода не учитываются."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, cost_price="500.00")
    # Продажа в сентябре
    await _create_sale(
        client, token, product_id=product_id, external_id="SEP",
        sold_at="2026-09-15T10:00:00Z",
    )
    # Продажа в октябре
    await _create_sale(
        client, token, product_id=product_id, external_id="OCT",
        sold_at="2026-10-15T10:00:00Z",
    )

    # Только сентябрь
    response = await client.get(
        f"/analytics/unit-economics?product_id={product_id}"
        "&from=2026-09-01T00:00:00Z&to=2026-09-30T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sales_count"] == 1
    assert data["gross_revenue"] == "1000.00"
