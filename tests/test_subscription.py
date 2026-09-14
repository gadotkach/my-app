from sqlalchemy import select

from app.models import User


async def _register(client, email: str = "sub@example.com") -> dict:
    response = await client.post(
        "/auth/register",
        json={"email": email, "name": "Sub", "password": "secret123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _login(client, email: str = "sub@example.com") -> str:
    response = await client.post(
        "/auth/login",
        json={"email": email, "name": "ignored", "password": "secret123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_trial_user_can_access_products(client):
    """Свежий пользователь получает trial → /products доступен."""
    await _register(client, "trial@example.com")
    token = await _login(client, "trial@example.com")

    response = await client.get(
        "/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_expired_user_gets_402(client, session):
    """Пользователь с истёкшим trial → 402 Payment Required."""
    await _register(client, "expired@example.com")

    # Принудительно ставим статус "expired" через прямую сессию
    user = await session.scalar(select(User).where(User.email == "expired@example.com"))
    assert user is not None
    user.subscription_status = "expired"
    await session.commit()

    token = await _login(client, "expired@example.com")

    response = await client.get(
        "/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 402
    assert "Subscription required" in response.json()["detail"]


async def test_none_user_gets_402(client, session):
    """Пользователь без trial (subscription_status='none') → 402."""
    await _register(client, "none@example.com")

    user = await session.scalar(select(User).where(User.email == "none@example.com"))
    assert user is not None
    user.subscription_status = "none"
    await session.commit()

    token = await _login(client, "none@example.com")

    response = await client.get(
        "/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 402


async def test_expired_user_can_still_call_users_me(client, session):
    """Даже с expired /users/me доступен — нужно фронту для показа «оформите подписку»."""
    await _register(client, "me@example.com")

    user = await session.scalar(select(User).where(User.email == "me@example.com"))
    assert user is not None
    user.subscription_status = "expired"
    await session.commit()

    token = await _login(client, "me@example.com")

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["subscription_status"] == "expired"
