"""Клиент Яндекс.Маркет Partner API.

Наследник BaseMarketplaceClient (расширяемая архитектура).
Авторизация: API-Key (Bearer) + business_id.

Документация: https://yandex.ru/dev/market/partner-api/
"""

from typing import Any

from app.marketplaces.base import BaseMarketplaceClient, MarketplaceClientError


class YandexMarketClientError(MarketplaceClientError):
    """Ошибка при обращении к Яндекс.Маркет API."""


class YandexMarketClient(BaseMarketplaceClient):
    code = "yandex_market"
    name = "Яндекс.Маркет"
    base_url = "https://api.partner.market.yandex.ru"
    default_timeout = 30.0

    auth_fields = [
        {"name": "api_key", "label": "API-токен", "type": "password"},
        {"name": "business_id", "label": "Business ID", "type": "text"},
    ]
    has_products = True
    has_sales = True
    has_ads = False

    def __init__(
        self,
        api_key: str,
        business_id: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = api_key
        self.business_id = business_id
        super().__init__(timeout=timeout)

    def _get_headers(self) -> dict[str, str]:
        return {
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _make_error(self, status_code: int, message: str) -> YandexMarketClientError:
        if status_code == 401:
            return YandexMarketClientError("Яндекс.Маркет: неверный токен (401)")
        if status_code == 403:
            return YandexMarketClientError("Яндекс.Маркет: доступ запрещён (403)")
        if status_code == 404:
            return YandexMarketClientError("Яндекс.Маркет: не найдено (404)")
        if status_code == 429:
            return YandexMarketClientError("Яндекс.Маркет: превышен лимит (429)")
        return YandexMarketClientError(f"Яндекс.Маркет error {status_code}: {message}")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        assert self._client is not None
        response = await self._client.get(path, params=params or {})
        return self._handle_response(response)

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        assert self._client is not None
        response = await self._client.post(path, json=payload)
        return self._handle_response(response)

    # --------------------------------------------------------
    # Специфика Яндекс.Маркет
    # --------------------------------------------------------

    async def verify_credentials(self) -> bool:
        """True, если токен валиден.

        GET /campaigns — возвращает список кампаний.
        """
        try:
            data = await self._get("/campaigns")
        except YandexMarketClientError:
            return False
        return isinstance(data, dict)

    async def list_campaigns(self) -> list[dict[str, Any]]:
        """Список кампаний селлера."""
        data = await self._get("/campaigns")
        return data.get("campaigns", []) if isinstance(data, dict) else []

    async def list_orders(
        self,
        campaign_id: int,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Список заказов кампании (v2)."""
        params: dict[str, Any] = {"limit": 50}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        data = await self._get(f"/campaigns/{campaign_id}/orders", params=params)
        return data.get("orders", []) if isinstance(data, dict) else []
