from datetime import datetime, timedelta, timezone


async def _register_and_login(client, email: str = "analytics@example.com") -> str:
    await client.post(
        "/auth/register",
        json={"email": email, "name": "Analytics", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": email, "name": "x", "password": "secret123"},
    )
    return login.json()["access_token"]


async def _create_sale(
    client,
    token: str,
    marketplace_code: str = "ozon",
    delivery_code: str | None = "cdek",
    external_id: str = "A-001",
    price: str = "1000.00",
    commission: str = "100.00",
    logistics: str = "50.00",
    sold_at: str = "2026-09-15T10:00:00Z",
) -> None:
    payload = {
        "marketplace_code": marketplace_code,
        "external_id": external_id,
        "quantity": 1,
        "price": price,
        "commission": commission,
        "logistics_cost": logistics,
        "sold_at": sold_at,
    }
    if delivery_code is not None:
        payload["delivery_service_code"] = delivery_code
    response = await client.post(
        "/sales",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


async def test_summary_empty(client):
    token = await _register_and_login(client)
    response = await client.get(
        "/analytics/summary?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sales_count"] == 0
    assert data["total_revenue"] == "0"


async def test_summary_with_sales(client):
    token = await _register_and_login(client)
    await _create_sale(client, token, price="1000.00", commission="100.00", logistics="50.00")
    await _create_sale(
        client, token, external_id="A-002", price="2000.00", commission="200.00", logistics="100.00"
    )

    response = await client.get(
        "/analytics/summary?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sales_count"] == 2
    assert data["total_revenue"] == "3000.00"
    assert data["total_commission"] == "300.00"
    assert data["total_logistics"] == "150.00"
    assert data["net_profit"] == "2550.00"


async def test_summary_filters_by_date(client):
    token = await _register_and_login(client)
    # Продажа в сентябре
    await _create_sale(client, token, external_id="SEP", sold_at="2026-09-15T10:00:00Z")
    # Продажа в октябре
    await _create_sale(client, token, external_id="OCT", sold_at="2026-10-15T10:00:00Z")

    # Только сентябрь
    response = await client.get(
        "/analytics/summary?from=2026-09-01T00:00:00Z&to=2026-09-30T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sales_count"] == 1
    assert data["total_revenue"] == "1000.00"


async def test_by_marketplace(client):
    token = await _register_and_login(client)
    await _create_sale(client, token, marketplace_code="ozon", external_id="O-1")
    await _create_sale(client, token, marketplace_code="ozon", external_id="O-2")
    await _create_sale(client, token, marketplace_code="wildberries", external_id="W-1")

    response = await client.get(
        "/analytics/by-marketplace?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    by_code = {row["marketplace_code"]: row for row in data}
    assert by_code["ozon"]["sales_count"] == 2
    assert by_code["ozon"]["total_revenue"] == "2000.00"
    assert by_code["wildberries"]["sales_count"] == 1
    assert by_code["wildberries"]["total_revenue"] == "1000.00"


async def test_analytics_requires_auth(client):
    response = await client.get(
        "/analytics/summary?from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z"
    )
    assert response.status_code == 401
