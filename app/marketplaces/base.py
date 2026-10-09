"""Базовый клиент маркетплейса (ABC)."""

from abc import ABC, abstractmethod
from typing import Any, Self

import httpx

from app.api_logger import log_request, log_response


class MarketplaceClientError(Exception):
    """Базовая ошибка маркетплейса."""


class BaseMarketplaceClient(ABC):
    """Базовый клиент маркетплейса (ABC).

    Наследники: OzonClient, WBClient, OzonAdsClient, YandexMarketClient.
    """

    code: str = "unknown"
    name: str = "Unknown"
    base_url: str = ""
    default_timeout: float = 30.0

    # Метаданные для UI (генерация форм)
    # auth_fields: список полей для ввода (name, label, type)
    auth_fields: list[dict[str, str]] = []
    has_products: bool = True
    has_sales: bool = True
    has_ads: bool = False

    # Флаг: нужно ли создавать единый AsyncClient
    # (WB создаёт клиент на каждый запрос — ему base не нужен)
    use_single_client: bool = True

    def __init__(self, timeout: float | None = None):
        self._timeout = timeout or self.default_timeout
        self._client: httpx.AsyncClient | None = None
        if self.use_single_client:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._get_headers(),
                event_hooks={
                    "request": [log_request],
                    "response": [log_response],
                },
            )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()

    @abstractmethod
    def _get_headers(self) -> dict[str, str]:
        """Заголовки для всех запросов."""
        ...

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET-запрос (по умолчанию — не поддерживается)."""
        raise NotImplementedError(f"{self.code}: _get не реализован")

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        """POST-запрос (по умолчанию — не поддерживается)."""
        raise NotImplementedError(f"{self.code}: _post не реализован")

    @abstractmethod
    async def verify_credentials(self) -> bool:
        """True, если credentials рабочие."""
        ...

    @abstractmethod
    def _make_error(self, status_code: int, message: str) -> MarketplaceClientError:
        """Создать специфичную ошибку наследника."""
        ...

    def _handle_response(self, response: httpx.Response) -> Any:
        """Общая обработка ответа."""
        if response.status_code == 401:
            raise self._make_error(401, "неверные credentials")
        if response.status_code == 403:
            raise self._make_error(403, "доступ запрещён")
        if response.status_code == 429:
            raise self._make_error(429, "превышен лимит запросов")
        if response.status_code >= 400:
            raise self._make_error(response.status_code, response.text[:200])
        if not response.content:
            return {}
        return response.json()
