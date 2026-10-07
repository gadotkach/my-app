from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx


class OzonClientError(Exception):
    """Ошибка при обращении к Ozon Seller API."""


class OzonClient:
    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self, client_id: str, api_key: str, timeout: float = 10.0):
        self.client_id = client_id
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={
                "Client-Id": client_id,
                "Api-Key": api_key,
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> "OzonClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(path, json=payload)
        if response.status_code == 401:
            raise OzonClientError("Ozon: неверный Client-Id или Api-Key")
        if response.status_code == 403:
            raise OzonClientError("Ozon: доступ запрещён (проверьте права Api-Key)")
        if response.status_code >= 400:
            raise OzonClientError(f"Ozon API error {response.status_code}: {response.text[:200]}")
        return cast(dict[str, Any], response.json())

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
            last_id = data.get("result", {}).get("last_id", "")
            if not last_id or not items:
                break
        return result

    async def get_product_info(self, product_ids: list[int]) -> list[dict[str, Any]]:
        """Детальная информация по товарам (название, SKU, описание)."""
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
        """Список FBS-отправлений за период. Ozon отдаёт постранично."""
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
        """Список отправлений за длинный период — разбивает на интервалы по 30 дней."""
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
        """Список FBO-отправлений за период (товары со склада Ozon)."""
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
        """FBO-отправления за длинный период — разбивает на интервалы по 30 дней."""
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
