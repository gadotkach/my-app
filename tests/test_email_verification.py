"""Тесты Email Verification (double opt-in).

Сценарии:
- register создаёт EmailVerificationToken
- verify-email подтверждает email
- невалидный / использованный / истёкший токен → 400
- resend-verification для неверифицированного → новый токен
- resend-verification для verified → «Email уже подтверждён»
"""

import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


async def _register(client, email: str) -> str:
    """Регистрирует юзера, возвращает access_token."""
    await client.post(
        "/auth/register",
        json={"email": email, "name": "Test", "password": "secret123"},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": "secret123"},
    )
    return resp.json()["access_token"]


# ============================================================
# Register создаёт EmailVerificationToken
# ============================================================


@pytest.mark.asyncio
async def test_register_creates_verification_token(client):
    """После register есть запись EmailVerificationToken."""
    with patch(
        "app.routers.auth.send_email_verification_email",
        new=AsyncMock(),
    ):
        await client.post(
            "/auth/register",
            json={"email": "v1@example.com", "name": "V1", "password": "secret123"},
        )

    # Проверяем через API (register возвращает UserRead с email_verified=false)
    resp = await client.post(
        "/auth/login",
        json={"email": "v1@example.com", "password": "secret123"},
    )
    access = resp.json()["access_token"]
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {access}"})
    assert me.json()["email_verified"] is False


# ============================================================
# Verify email
# ============================================================


@pytest.mark.asyncio
async def test_verify_email_success(client, engine):
    """Валидный токен подтверждает email."""
    with patch(
        "app.routers.auth.send_email_verification_email",
        new=AsyncMock(),
    ):
        access = await _register(client, "v2@example.com")

        # Создаём токен через resend (он вернёт 200)
        await client.post(
            "/auth/resend-verification",
            headers={"Authorization": f"Bearer {access}"},
        )

    # Достаём raw-токен из БД? Нет — у нас только hash. Создаём свой.
    raw = secrets.token_urlsafe(32)
    from app.routers.auth import _hash_email_token

    token_hash = _hash_email_token(raw)

    async with engine.begin() as conn:
        from sqlalchemy import text as sql_text

        await conn.execute(
            sql_text(
                "DELETE FROM email_verification_tokens "
                "WHERE user_id = (SELECT id FROM users WHERE email = :email)"
            ),
            {"email": "v2@example.com"},
        )
        await conn.execute(
            sql_text(
                "INSERT INTO email_verification_tokens "
                "(user_id, token_hash, expires_at, created_at) VALUES "
                "((SELECT id FROM users WHERE email = :email), :h, :exp, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "email": "v2@example.com",
                "h": token_hash,
                "exp": datetime.now(UTC) + timedelta(hours=24),
            },
        )

    resp = await client.post("/auth/verify-email", json={"token": raw})
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == "Email успешно подтверждён."

    # Проверяем флаг
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {access}"})
    assert me.json()["email_verified"] is True


@pytest.mark.asyncio
async def test_verify_email_invalid_token(client):
    """Невалидный токен → 400."""
    resp = await client.post("/auth/verify-email", json={"token": "NONEXISTENT_TOKEN"})
    assert resp.status_code == 400
    assert "недействительна" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_verify_email_used_token(client, engine):
    """Повторное использование токена → 400."""
    with patch(
        "app.routers.auth.send_email_verification_email",
        new=AsyncMock(),
    ):
        await client.post(
            "/auth/register",
            json={"email": "used@example.com", "name": "U", "password": "secret123"},
        )

    # Первое подтверждение
    from app.routers.auth import _hash_email_token

    raw = secrets.token_urlsafe(32)
    h = _hash_email_token(raw)

    from sqlalchemy import text as sql_text

    async with engine.begin() as conn:
        await conn.execute(
            sql_text(
                "DELETE FROM email_verification_tokens "
                "WHERE user_id = (SELECT id FROM users WHERE email = :email)"
            ),
            {"email": "used@example.com"},
        )
        await conn.execute(
            sql_text(
                "INSERT INTO email_verification_tokens "
                "(user_id, token_hash, expires_at, created_at) VALUES "
                "((SELECT id FROM users WHERE email = :email), :h, :exp, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "email": "used@example.com",
                "h": h,
                "exp": datetime.now(UTC) + timedelta(hours=24),
            },
        )

    r1 = await client.post("/auth/verify-email", json={"token": raw})
    assert r1.status_code == 200

    r2 = await client.post("/auth/verify-email", json={"token": raw})
    assert r2.status_code == 400
    assert "уже использована" in r2.json()["detail"].lower()


# ============================================================
# Expired token
# ============================================================


@pytest.mark.asyncio
async def test_verify_email_expired_token(client, engine):
    """Истёкший токен → 400."""
    with patch(
        "app.routers.auth.send_email_verification_email",
        new=AsyncMock(),
    ):
        await client.post(
            "/auth/register",
            json={"email": "exp@example.com", "name": "E", "password": "secret123"},
        )

    from app.routers.auth import _hash_email_token

    raw = secrets.token_urlsafe(32)
    h = _hash_email_token(raw)
    past = datetime.now(UTC) - timedelta(hours=1)

    from sqlalchemy import text as sql_text

    async with engine.begin() as conn:
        await conn.execute(
            sql_text(
                "DELETE FROM email_verification_tokens "
                "WHERE user_id = (SELECT id FROM users WHERE email = :email)"
            ),
            {"email": "exp@example.com"},
        )
        await conn.execute(
            sql_text(
                "INSERT INTO email_verification_tokens "
                "(user_id, token_hash, expires_at, created_at) VALUES "
                "((SELECT id FROM users WHERE email = :email), :h, :exp, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "email": "exp@example.com",
                "h": h,
                "exp": past,
            },
        )

    resp = await client.post("/auth/verify-email", json={"token": raw})
    assert resp.status_code == 400
    assert "истекла" in resp.json()["detail"].lower()


# ============================================================
# Resend
# ============================================================


@pytest.mark.asyncio
async def test_resend_verification_for_unverified(client):
    """Resend для неверифицированного → 200 + письмо."""
    with patch(
        "app.routers.auth.send_email_verification_email",
        new=AsyncMock(),
    ) as mock_send:
        access = await _register(client, "resend@example.com")

        resp = await client.post(
            "/auth/resend-verification",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        assert "отправлено повторно" in resp.json()["detail"].lower()
        assert mock_send.called


@pytest.mark.asyncio
async def test_resend_verification_for_verified(client, engine):
    """Resend для verified → «Email уже подтверждён»."""
    with patch(
        "app.routers.auth.send_email_verification_email",
        new=AsyncMock(),
    ):
        access = await _register(client, "resend2@example.com")

    # Принудительно ставим email_verified
    from sqlalchemy import text as sql_text

    async with engine.begin() as conn:
        await conn.execute(
            sql_text("UPDATE users SET email_verified = true WHERE email = 'resend2@example.com'")
        )

    resp = await client.post(
        "/auth/resend-verification",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    assert "уже подтверждён" in resp.json()["detail"].lower()
