async def test_create_user(client):
    response = await client.post(
        "/users",
        json={"email": "alice@example.com", "name": "Alice", "password": "secret123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["name"] == "Alice"
    assert "hashed_password" not in data
    assert "password" not in data


async def test_create_duplicate_email(client):
    payload = {"email": "bob@example.com", "name": "Bob", "password": "secret123"}
    first = await client.post("/users", json=payload)
    assert first.status_code == 201

    second = await client.post("/users", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "User with this email already exists"


async def test_create_invalid_email(client):
    response = await client.post(
        "/users",
        json={"email": "not-an-email", "name": "X", "password": "secret123"},
    )
    assert response.status_code == 422


async def test_list_users_empty(client):
    response = await client.get("/users")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_users(client):
    await client.post(
        "/users",
        json={"email": "u1@example.com", "name": "U1", "password": "secret123"},
    )
    await client.post(
        "/users",
        json={"email": "u2@example.com", "name": "U2", "password": "secret123"},
    )

    response = await client.get("/users")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {u["email"] for u in data} == {"u1@example.com", "u2@example.com"}


async def test_get_user_not_found(client):
    response = await client.get("/users/9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


async def test_get_user_by_id(client):
    created = await client.post(
        "/users",
        json={"email": "carol@example.com", "name": "Carol", "password": "secret123"},
    )
    user_id = created.json()["id"]

    response = await client.get(f"/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["email"] == "carol@example.com"
