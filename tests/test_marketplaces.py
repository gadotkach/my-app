async def test_list_marketplaces_public(client):
    response = await client.get("/marketplaces")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 5
    codes = {m["code"] for m in data}
    assert "ozon" in codes
    assert "avito" in codes


async def test_create_marketplace_requires_auth(client):
    response = await client.post(
        "/marketplaces",
        json={"code": "new_market", "name": "New Market"},
    )
    assert response.status_code == 401


async def test_create_marketplace(client):
    # Сначала регистрируемся, чтобы получить токен
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
        "/marketplaces",
        json={"code": "new_market", "name": "New Market"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["code"] == "new_market"
    assert data["name"] == "New Market"


async def test_create_marketplace_duplicate(client):
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
        "/marketplaces",
        json={"code": "avito", "name": "Avito"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
