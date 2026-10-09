"""Тесты Яндекс OAuth (redirect + callback)."""

import secrets
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import settings
from app.routers.auth import YANDEX_STATE_COOKIE_NAME


def test_build_authorize_url() -> None:
    """URL содержит client_id, redirect_uri, state."""
    from app.yandex_oauth import build_authorize_url

    url = build_authorize_url("test_state")
    assert "oauth.yandex.ru/authorize" in url
    assert f"client_id={settings.yandex_oauth_client_id}" in url
    assert "state=test_state" in url
    assert "redirect_uri=" in url


def test_extract_email_priority() -> None:
    """default_email имеет приоритет над emails[0]."""
    from app.yandex_oauth import extract_email

    assert extract_email({"default_email": "a@b.ru"}) == "a@b.ru"
    assert extract_email({"emails": ["c@d.ru"]}) == "c@d.ru"
    assert extract_email({}) is None


def test_extract_name_priority() -> None:
    """real_name > display_name > first_name > login > 'Пользователь'."""
    from app.yandex_oauth import extract_name

    assert extract_name({"real_name": "Иван Иванов"}) == "Иван Иванов"
    assert extract_name({"display_name": "Ваня"}) == "Ваня"
    assert extract_name({"first_name": "Иван"}) == "Иван"
    assert extract_name({"login": "user123"}) == "user123"
    assert extract_name({}) == "Пользователь"


@pytest.mark.asyncio
async def test_yandex_redirect_sets_state_cookie(client: AsyncClient) -> None:
    """GET /auth/yandex/redirect → 302 на Яндекс + HttpOnly cookie state."""
    response = await client.get("/auth/yandex/redirect", follow_redirects=False)

    assert response.status_code == 302
    assert "oauth.yandex.ru/authorize" in response.headers["location"]
    assert "state=" in response.headers["location"]
    assert YANDEX_STATE_COOKIE_NAME in response.cookies


@pytest.mark.asyncio
async def test_yandex_callback_invalid_state(client: AsyncClient) -> None:
    """Callback с невалидным state → 400 (CSRF)."""
    response = await client.get(
        "/auth/yandex/callback",
        params={"code": "fake_code", "state": "wrong_state"},
        cookies={YANDEX_STATE_COOKIE_NAME: "correct_state"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_yandex_callback_creates_new_user(client: AsyncClient) -> None:
    """Callback для нового юзера → создаёт User с yandex_id, редирект на фронт."""
    state = secrets.token_urlsafe(32)

    fake_user_info = {
        "id": "999999999",
        "default_email": "oauth-new@example.com",
        "real_name": "OAuth User",
    }

    with (
        patch("app.routers.auth.exchange_code", new=AsyncMock(return_value="fake_token")),
        patch("app.routers.auth.fetch_user_info", new=AsyncMock(return_value=fake_user_info)),
    ):
        response = await client.get(
            "/auth/yandex/callback",
            params={"code": "fake_code", "state": state},
            cookies={YANDEX_STATE_COOKIE_NAME: state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert "/auth/yandex/complete#access_token=" in response.headers["location"]

    # Проверка: юзер создан — повторная регистрация того же email даёт 409
    register_response = await client.post(
        "/auth/register",
        json={
            "email": "oauth-new@example.com",
            "name": "Test",
            "password": "secret123",
        },
    )
    assert register_response.status_code == 409
