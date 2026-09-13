async def _register_and_login(client, email: str = "seller@example.com") -> str:
    await client.post(
        "/auth/register",
        json={"email": email, "name": "Seller", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": email, "name": "x", "password": "secret123"},
    )
    return login.json()["access_token"]


async def test_create_sale_with_delivery(client):
    token = await _register_and_login(client)

    response = await client.post(
        "/sales",
        json={
            "marketplace_code": "ozon",
            "delivery_service_code": "cdek",
            "external_id": "OZ-001",
            "quantity": 1,
            "price": "1500.00",
            "commission": "225.00",
            "logistics_cost": "150.00",
            "sold_at": "2026-09-13T10:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["marketplace_id"] is not None
    assert data["delivery_service_id"] is not None
    assert data["external_id"] == "OZ-001"
    assert data["price"] == "1500.00"


async def test_create_sale_unknown_delivery_service(client):
    token = await _register_and_login(client)

    response = await client.post(
        "/sales",
        json={
            "marketplace_code": "ozon",
            "delivery_service_code": "nonexistent",
            "external_id": "OZ-002",
            "quantity": 1,
            "price": "100.00",
            "sold_at": "2026-09-13T11:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "Unknown delivery service code" in response.json()["detail"]


async def test_list_sales(client):
    token = await _register_and_login(client)

    await client.post(
        "/sales",
        json={
            "marketplace_code": "wildberries",
            "delivery_service_code": "boxberry",
            "external_id": "WB-001",
            "quantity": 2,
            "price": "3000.00",
            "sold_at": "2026-09-13T12:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    response = await client.get("/sales", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["external_id"] == "WB-001"
