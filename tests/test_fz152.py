"""Тесты ФЗ-152: согласия, экспорт, удаление."""

from httpx import AsyncClient
from sqlalchemy import select

# ============================================================
# Consent API
# ============================================================


async def test_register_creates_consents(client: AsyncClient, engine):
    """При регистрации создаются 2 consent: pd_processing, oferta."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    response = await client.post(
        "/auth/register",
        json={
            "email": "fz152-1@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )
    assert response.status_code == 201

    # Проверим в БД (через test engine, не AsyncSessionLocal)
    from app.models import User, UserConsent

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == "fz152-1@example.com"))
        assert user is not None
        consents = (
            await s.scalars(select(UserConsent).where(UserConsent.user_id == user.id))
        ).all()
        types = sorted(c.consent_type for c in consents)
        assert types == ["oferta", "pd_processing"]
        for c in consents:
            assert c.granted_at is not None
            assert c.revoked_at is None


async def test_consent_status(client: AsyncClient):
    """GET /auth/consent/status возвращает согласия юзера."""
    # Регистрация
    await client.post(
        "/auth/register",
        json={
            "email": "fz152-2@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )

    # Логин
    login = await client.post(
        "/auth/login",
        json={"email": "fz152-2@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Status
    response = await client.get("/auth/consent/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    consents = data["consents"]
    types = sorted(c["consent_type"] for c in consents)
    assert types == ["oferta", "pd_processing"]


async def test_consent_accept(client: AsyncClient):
    """POST /auth/consent/accept создаёт новое согласие."""
    await client.post(
        "/auth/register",
        json={
            "email": "fz152-3@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "fz152-3@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Accept marketing
    response = await client.post(
        "/auth/consent/accept",
        json={"consent_type": "marketing"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["consent_type"] == "marketing"
    assert data["revoked_at"] is None


async def test_consent_revoke(client: AsyncClient):
    """DELETE /auth/consent/{type} — soft revoke (revoked_at)."""
    await client.post(
        "/auth/register",
        json={
            "email": "fz152-4@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "fz152-4@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Revoke oferta
    response = await client.delete("/auth/consent/oferta", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["consent_type"] == "oferta"
    assert data["revoked_at"] is not None


# ============================================================
# Export
# ============================================================


async def test_export_me(client: AsyncClient):
    """GET /users/me/export возвращает все данные."""
    await client.post(
        "/auth/register",
        json={
            "email": "fz152-5@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "fz152-5@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/users/me/export", headers=headers)
    assert response.status_code == 200
    data = response.json()

    # Проверки
    assert "user" in data
    assert data["user"]["email"] == "fz152-5@example.com"
    assert "products" in data
    assert "sales" in data
    assert "integrations" in data
    assert "consents" in data
    assert "exported_at" in data

    # Consents — 2
    consents = data["consents"]
    types = sorted(c["consent_type"] for c in consents)
    assert types == ["oferta", "pd_processing"]


# ============================================================
# Delete (soft)
# ============================================================


async def test_delete_me(client: AsyncClient):
    """DELETE /users/me — soft delete (deleted_at + email анонимизирован)."""
    await client.post(
        "/auth/register",
        json={
            "email": "fz152-6@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "fz152-6@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.delete("/users/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert "deletion_scheduled_at" in data
    assert "detail" in data


async def test_login_after_delete_401(client: AsyncClient):
    """После soft delete — login невозможен (email анонимизирован)."""
    await client.post(
        "/auth/register",
        json={
            "email": "fz152-7@example.com",
            "name": "FZ152",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "fz152-7@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Delete
    response = await client.delete("/users/me", headers=headers)
    assert response.status_code == 200

    # Попытка логина
    response = await client.post(
        "/auth/login",
        json={"email": "fz152-7@example.com", "password": "secret123"},
    )
    assert response.status_code == 401
