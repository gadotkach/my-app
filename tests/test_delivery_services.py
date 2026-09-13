async def test_list_delivery_services_public(client):
    response = await client.get("/delivery-services")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 4
    codes = {s["code"] for s in data}
    assert "cdek" in codes


async def test_create_delivery_service(client):
    await client.post(
        "/auth/register",
        json={"email": "seller@example.com", "name": "Seller", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "seller@example.com", "name": "x", "password": "secret123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/delivery-services",
        json={"code": "5post", "name": "5Post"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["code"] == "5post"


async def test_create_delivery_service_duplicate(client):
    await client.post(
        "/auth/register",
        json={"email": "seller@example.com", "name": "Seller", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "seller@example.com", "name": "x", "password": "secret123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/delivery-services",
        json={"code": "cdek", "name": "СДЭК"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
