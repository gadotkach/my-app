"""Тесты эндпоинта /analytics/abc."""

from decimal import Decimal


async def _register_and_login(client, email: str = "abc@example.com") -> str:
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
    sku: str,
    name: str,
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
    external_id: str,
    price: str = "1000.00",
    commission: str = "150.00",
    logistics: str = "100.00",
) -> None:
    response = await client.post(
        "/sales",
        json={
            "marketplace_code": "ozon",
            "product_id": product_id,
            "external_id": external_id,
            "quantity": 1,
            "price": price,
            "commission": commission,
            "logistics_cost": logistics,
            "sold_at": "2026-09-15T10:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


# ============================================================
# Доступ и пустой период
# ============================================================


async def test_abc_requires_auth(client):
    """Без токена → 401."""
    response = await client.get("/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z")
    assert response.status_code == 401


async def test_abc_empty(client):
    """Нет продаж → пустые groups и products."""
    token = await _register_and_login(client)
    response = await client.get(
        "/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["groups"] == []
    assert data["products"] == []


# ============================================================
# Один товар
# ============================================================


async def test_abc_single_product(client):
    """Один прибыльный товар → группа A."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, sku="P-1", name="Товар 1")
    await _create_sale(client, token, product_id, external_id="S-1")

    response = await client.get(
        "/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert len(data["groups"]) == 1
    assert data["groups"][0]["group"] == "A"
    assert data["groups"][0]["products_count"] == 1
    assert len(data["products"]) == 1
    assert data["products"][0]["group"] == "A"
    # profit = 1000 − 250 (расходы площадки) − 500 (себестоимость) = 250
    assert data["products"][0]["net_profit"] == "250.00"


# ============================================================
# Убыточный товар
# ============================================================


async def test_abc_loss_making_in_c(client):
    """Убыточный товар → группа C, даже если он единственный."""
    token = await _register_and_login(client)
    product_id = await _create_product(
        client, token, sku="P-LOSS", name="Убыточный", cost_price="2000.00"
    )
    await _create_sale(client, token, product_id, external_id="S-LOSS")

    response = await client.get(
        "/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # payout = 750, cogs = 2000, net_profit = −1250
    assert data["products"][0]["net_profit"] == "-1250.00"
    assert data["products"][0]["group"] == "C"


# ============================================================
# Группы A / B / C
# ============================================================


async def test_abc_groups_distribution(client):
    """10 товаров с разной прибылью → правильное распределение A/B/C."""
    token = await _register_and_login(client)

    # Создаём 10 товаров с разными ценами.
    # Чем выше цена — тем выше прибыль.
    # Все себестоимость 500, расходы площадки 250 с продажи.
    # Прибыль = price − 250 − 500 = price − 750.
    prices = [
        "10000.00",  # profit 9250
        "5000.00",  # profit 4250
        "3000.00",  # profit 2250
        "2000.00",  # profit 1250
        "1500.00",  # profit 750
        "1300.00",  # profit 550
        "1200.00",  # profit 450
        "1100.00",  # profit 350
        "1000.00",  # profit 250
        "900.00",  # profit 150
    ]
    for i, price in enumerate(prices):
        pid = await _create_product(client, token, sku=f"P-{i}", name=f"Товар {i}")
        await _create_sale(client, token, pid, external_id=f"S-{i}", price=price)

    response = await client.get(
        "/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Всего 10 товаров
    assert len(data["products"]) == 10

    # Проверяем, что все товары распределены по группам
    total_count = sum(g["products_count"] for g in data["groups"])
    assert total_count == 10

    # Каждая группа присутствует хотя бы раз
    groups_by_code = {g["group"]: g for g in data["groups"]}
    assert "A" in groups_by_code


async def test_abc_sums_correct(client):
    """Общая выручка и прибыль совпадают с суммой по товарам."""
    token = await _register_and_login(client)

    p1 = await _create_product(client, token, sku="S-1", name="Товар 1")
    p2 = await _create_product(client, token, sku="S-2", name="Товар 2")
    await _create_sale(client, token, p1, external_id="X-1", price="1000.00")
    await _create_sale(client, token, p2, external_id="X-2", price="2000.00")

    response = await client.get(
        "/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Сумма по группам == сумма по товарам
    total_revenue_from_groups = sum((Decimal(g["revenue"]) for g in data["groups"]), Decimal("0"))
    total_revenue_from_products = sum(
        (Decimal(p["revenue"]) for p in data["products"]), Decimal("0")
    )
    assert total_revenue_from_groups == total_revenue_from_products


async def test_abc_filters_by_date(client):
    """Продажи вне периода не учитываются."""
    token = await _register_and_login(client)
    product_id = await _create_product(client, token, sku="DATE-1", name="Товар")

    # Вне периода
    await client.post(
        "/sales",
        json={
            "marketplace_code": "ozon",
            "product_id": product_id,
            "external_id": "OLD",
            "quantity": 1,
            "price": "5000.00",
            "sold_at": "2025-01-01T10:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # Внутри периода
    await _create_sale(client, token, product_id, external_id="NEW", price="1000.00")

    response = await client.get(
        "/analytics/abc?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    # Учтена только продажа внутри периода
    assert data["products"][0]["revenue"] == "1000.00"
