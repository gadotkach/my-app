from unittest.mock import AsyncMock, patch


async def test_sync_products_requires_auth(client):
    response = await client.post("/integrations/ozon/sync/products")
    assert response.status_code == 401


async def test_sync_products_ozon_not_connected(client):
    await client.post(
        "/auth/register",
        json={"email": "noozon@example.com", "name": "X", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "noozon@example.com", "name": "x", "password": "secret123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/integrations/ozon/sync/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Ozon is not connected for this user"


async def _connect_ozon(client, token: str) -> None:
    with patch("app.routers.integrations.OzonClient") as mock_cls:
        mock_instance = mock_cls.return_value.__aenter__.return_value
        mock_instance.get_seller_info = AsyncMock(return_value={"company": {}})
        response = await client.post(
            "/integrations/ozon/connect",
            json={
                "marketplace_code": "ozon",
                "client_id": "123456",
                "api_key": "test_api_key",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201, response.text


async def test_sync_products_no_items(client):
    await client.post(
        "/auth/register",
        json={"email": "empty@example.com", "name": "E", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "empty@example.com", "name": "x", "password": "secret123"},
    )
    token = login.json()["access_token"]

    await _connect_ozon(client, token)

    with patch("app.routers.integrations.OzonClient") as mock_cls:
        mock_instance = mock_cls.return_value.__aenter__.return_value
        mock_instance.list_products = AsyncMock(return_value=[])
        mock_instance.get_product_info = AsyncMock(return_value=[])

        response = await client.post(
            "/integrations/ozon/sync/products",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"synced": 0, "created": 0, "updated": 0}


async def test_sync_products_creates_products(client):
    await client.post(
        "/auth/register",
        json={"email": "withproducts@example.com", "name": "W", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "withproducts@example.com", "name": "x", "password": "secret123"},
    )
    token = login.json()["access_token"]

    await _connect_ozon(client, token)

    with patch("app.routers.integrations.OzonClient") as mock_cls:
        mock_instance = mock_cls.return_value.__aenter__.return_value
        mock_instance.list_products = AsyncMock(
            return_value=[{"product_id": 101}, {"product_id": 102}]
        )
        mock_instance.get_product_info = AsyncMock(
            return_value=[
                {"id": 101, "sku": "SKU-001", "name": "Кружка", "description": "Керамика"},
                {"id": 102, "sku": "SKU-002", "name": "Тарелка", "description": None},
            ]
        )

        response = await client.post(
            "/integrations/ozon/sync/products",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 2
    assert data["created"] == 2
    assert data["updated"] == 0

    response = await client.get(
        "/products", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    products = response.json()
    assert len(products) == 2
    skus = {p["sku"] for p in products}
    assert skus == {"SKU-001", "SKU-002"}
