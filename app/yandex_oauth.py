"""Клиент Yandex OAuth (Яндекс ID).

Документация: https://yandex.ru/dev/id/doc/ru/
"""

from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

YANDEX_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_USERINFO_URL = "https://login.yandex.ru/info"


def build_authorize_url(state: str) -> str:
    """Формирует URL для редиректа пользователя на Яндекс ID."""
    params = {
        "response_type": "code",
        "client_id": settings.yandex_oauth_client_id,
        "redirect_uri": settings.yandex_oauth_redirect_uri,
        "state": state,
    }
    return f"{YANDEX_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> str:
    """Обменивает authorization code на access_token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            YANDEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.yandex_oauth_client_id,
                "client_secret": settings.yandex_oauth_client_secret,
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return str(data["access_token"])


async def fetch_user_info(access_token: str) -> dict[str, Any]:
    """Получает информацию о пользователе из Яндекса."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            YANDEX_USERINFO_URL,
            params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def extract_email(user_info: dict[str, Any]) -> str | None:
    """Приоритет: default_email -> emails[0]."""
    default_email = user_info.get("default_email")
    if default_email:
        return str(default_email)
    emails = user_info.get("emails") or []
    if emails:
        return str(emails[0])
    return None


def extract_name(user_info: dict[str, Any]) -> str:
    """Приоритет: real_name -> display_name -> first_name -> login -> 'Пользователь'."""
    for key in ("real_name", "display_name", "first_name"):
        value = user_info.get(key)
        if value:
            return str(value)
    login = user_info.get("login")
    if login:
        return str(login)
    return "Пользователь"
