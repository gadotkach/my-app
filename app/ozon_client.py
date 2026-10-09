"""Клиент Ozon Seller API.

Наследник BaseMarketplaceClient (расширяемая архитектура).
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.marketplaces.base import BaseMarketplaceClient, MarketplaceClientError


class OzonClientError(MarketplaceClientError):
    """Ошибка при обращении к Ozon Seller API."""


class OzonClient(BaseMarketplaceClient):
    code = "ozon"
    name = "Ozon"
    base_url = "https://api-seller.ozon.ru"
    default_timeout = 10.0

    auth_fields = [
        {"name": "client_id", "label": "Client-Id", "type": "text"},
        {"name": "api_key", "label": "API-Key", "type": "password"},
    ]
    has_products = True
    has_sales = True
    has_ads = False

    def __init__(self, client_id: str, api_key: str, timeout: float | None = None):
        self.client_id = client_id
        self.api_key = api_key
        super().__init__(timeout=timeout)

    def _get_headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _make_error(self, status_code: int, message: str) -> OzonClientError:
        if status_code == 401:
            return OzonClientError("Ozon: неверный Client-Id или Api-Key")
        if status_code == 403:
            return OzonClientError("Ozon: доступ запрещён (проверьте права Api-Key)")
        return OzonClientError(f"Ozon API error {status_code}: {message}")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError("Ozon Seller API не использует GET")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None  # use_single_client=True
        response = await self._client.post(path, json=payload)
        return cast(dict[str, Any], self._handle_response(response))

    # --------------------------------------------------------
    # Специфика Ozon
    # --------------------------------------------------------

    async def get_seller_info(self) -> dict[str, Any]:
        """Проверка ключей — возвращает информацию о продавце."""
        return await self._post("/v1/seller/info", {})

    async def list_products(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Список товаров продавца. Ozon отдаёт постранично, до 1000 за раз."""
        result: list[dict[str, Any]] = []
        last_id = ""
        while True:
            payload: dict[str, Any] = {"filter": {"visibility": "ALL"}, "limit": limit}
            if last_id:
                payload["last_id"] = last_id
            data = await self._post("/v3/product/list", payload)
            items = data.get("result", {}).get("items", [])
            result.extend(items)
            if len(items) < limit:
                break
            last_id = data.get("result", {}).get("last_id", "")
            if not last_id:
                break
        return result

    async def get_product_info(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Детальная информация по товарам."""
        if not product_ids:
            return []
        data = await self._post(
            "/v3/product/info/list",
            {"product_id": product_ids},
        )
        return cast(list[dict[str, Any]], data.get("items", []))

    async def list_postings(
        self,
        since: str,
        to: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Список FBS-отправлений за период."""
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload: dict[str, Any] = {
                "dir": "DESC",
                "filter": {"since": since, "to": to},
                "limit": limit,
                "offset": offset,
                "with": {"analytics_data": False, "financial_data": True},
            }
            data = await self._post("/v3/posting/fbs/list", payload)
            postings = data.get("result", {}).get("postings", [])
            result.extend(postings)
            has_next = data.get("result", {}).get("has_next", False)
            if not has_next or not postings:
                break
            offset += limit
        return result

    async def list_postings_for_range(
        self,
        since: str,
        to: str,
    ) -> list[dict[str, Any]]:
        """Список отправлений за длинный период (30-дневные интервалы)."""
        start = datetime.fromisoformat(since.replace("Z", "+00:00"))
        end = datetime.fromisoformat(to.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        chunk = timedelta(days=30)
        all_postings: list[dict[str, Any]] = []
        current = start
        while current < end:
            chunk_end = min(current + chunk, end)
            postings = await self.list_postings(
                since=current.isoformat().replace("+00:00", "Z"),
                to=chunk_end.isoformat().replace("+00:00", "Z"),
            )
            all_postings.extend(postings)
            current = chunk_end + timedelta(seconds=1)
        return all_postings

    async def list_fbo_postings(
        self,
        since: str,
        to: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Список FBO-отправлений за период."""
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload: dict[str, Any] = {
                "dir": "DESC",
                "filter": {"since": since, "to": to},
                "limit": limit,
                "offset": offset,
                "with": {"analytics_data": False, "financial_data": True},
            }
            data = await self._post("/v2/posting/fbo/list", payload)
            postings = data.get("result", [])
            if not isinstance(postings, list):
                postings = []
            result.extend(postings)
            if len(postings) < limit:
                break
            offset += limit
        return result

    async def list_fbo_postings_for_range(
        self,
        since: str,
        to: str,
    ) -> list[dict[str, Any]]:
        """FBO-отправления за длинный период (30-дневные интервалы)."""
        start = datetime.fromisoformat(since.replace("Z", "+00:00"))
        end = datetime.fromisoformat(to.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)

        chunk = timedelta(days=30)
        all_postings: list[dict[str, Any]] = []
        current = start
        while current < end:
            chunk_end = min(current + chunk, end)
            postings = await self.list_fbo_postings(
                since=current.isoformat().replace("+00:00", "Z"),
                to=chunk_end.isoformat().replace("+00:00", "Z"),
            )
            all_postings.extend(postings)
            current = chunk_end + timedelta(seconds=1)
        return all_postings

    async def verify_credentials(self) -> bool:
        """True, если ключи рабочие."""
        try:
            await self.get_seller_info()
        except OzonClientError:
            return False
        return True
