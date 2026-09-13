async def test_register(client):
    response = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "name": "New", "password": "secret123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert "password" not in data
    assert "hashed_password" not in data


async def test_register_duplicate(client):
    payload = {"email": "dup@example.com", "name": "Dup", "password": "secret123"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_success(client):
    await client.post(
        "/auth/register",
        json={"email": "log@example.com", "name": "Log", "password": "secret123"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "log@example.com", "name": "x", "password": "secret123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client):
    await client.post(
        "/auth/register",
        json={"email": "wrong@example.com", "name": "W", "password": "secret123"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "wrong@example.com", "name": "x", "password": "WRONG"},
    )
    assert response.status_code == 401


async def test_me_requires_token(client):
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_me_with_token(client):
    await client.post(
        "/auth/register",
        json={"email": "me@example.com", "name": "Me", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "me@example.com", "name": "x", "password": "secret123"},
    )
    token = login.json()["access_token"]

    response = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


async def test_refresh_success(client):
    await client.post(
        "/auth/register",
        json={"email": "ref@example.com", "name": "R", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "ref@example.com", "name": "x", "password": "secret123"},
    )
    assert login.status_code == 200
    assert "refresh_token" in login.cookies

    response = await client.post("/auth/refresh")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_refresh_without_cookie(client):
    response = await client.post("/auth/refresh")
    assert response.status_code == 401
    assert response.json()["detail"] == "No refresh token"


async def test_logout_revokes_refresh(client):
    await client.post(
        "/auth/register",
        json={"email": "logout@example.com", "name": "L", "password": "secret123"},
    )
    login = await client.post(
        "/auth/login",
        json={"email": "logout@example.com", "name": "x", "password": "secret123"},
    )
    assert login.status_code == 200
    assert "refresh_token" in login.cookies

    logout = await client.post("/auth/logout")
    assert logout.status_code == 204

    # После logout refresh должен вернуть 401
    response = await client.post("/auth/refresh")
    assert response.status_code == 401
