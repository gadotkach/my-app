"""Клиент Wildberries Seller API.

Наследник BaseMarketplaceClient (расширяемая архитектура).
WB использует разные base_url для разных API — создаём AsyncClient на каждый запрос.
"""

from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.api_logger import log_request, log_response
from app.marketplaces.base import BaseMarketplaceClient, MarketplaceClientError


class WBClientError(MarketplaceClientError):
    """Ошибка при обращении к Wildberries API."""


class WBClient(BaseMarketplaceClient):
    code = "wildberries"
    name = "Wildberries"
    base_url = ""  # не используется (у WB несколько URL)
    default_timeout = 30.0
    use_single_client = False  # создаём AsyncClient на каждый запрос

    auth_fields = [
        {"name": "api_key", "label": "API-токен", "type": "password"},
    ]
    has_products = True
    has_sales = True
    has_ads = False

    COMMON_URL = "https://common-api.wildberries.ru"
    CONTENT_URL = "https://content-api.wildberries.ru"
    STATISTICS_URL = "https://statistics-api.wildberries.ru"
    FINANCE_URL = "https://finance-api.wildberries.ru"

    def __init__(self, api_token: str, timeout: float | None = None):
        self.api_token = api_token
        super().__init__(timeout=timeout)

    def _get_headers(self) -> dict[str, str]:
        # WB не использует префикс Bearer
        return {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
        }

    def _make_error(self, status_code: int, message: str) -> WBClientError:
        if status_code == 401:
            return WBClientError("WB: неверный токен (401 Unauthorized)")
        if status_code == 403:
            return WBClientError(
                "WB: 403 Forbidden — нет данных за период или нет прав на «Финансы»"
            )
        if status_code == 429:
            return WBClientError(
                "WB: превышен лимит запросов (429). Для Базового токена лимит очень жёсткий"
            )
        return WBClientError(f"WB API error {status_code}: {message}")

    def _new_client(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url,
            timeout=self._timeout,
            event_hooks={
                "request": [log_request],
                "response": [log_response],
            },
        )

    async def _get_url(
        self,
        base_url: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        async with self._new_client(base_url) as client:
            response = await client.get(path, headers=self._get_headers(), params=params or {})
        return self._handle_response(response)

    async def _post_url(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        async with self._new_client(base_url) as client:
            response = await client.post(path, headers=self._get_headers(), json=payload)
        return self._handle_response(response)

    # --------------------------------------------------------
    # Проверка токена
    # --------------------------------------------------------

    async def ping(self) -> bool:
        try:
            data = await self._get_url(self.COMMON_URL, "/ping")
        except WBClientError:
            return False
        return bool(data.get("Status") == "OK" or "TS" in data)

    async def verify_credentials(self) -> bool:
        return await self.ping()

    # --------------------------------------------------------
    # Товары (Content API)
    # --------------------------------------------------------

    async def list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        """Список карточек товаров. Cursor-пагинация. Лимит 100 за запрос."""
        result: list[dict[str, Any]] = []
        cursor: dict[str, Any] = {"limit": limit}

        while True:
            payload = {
                "settings": {
                    "cursor": cursor,
                    "filter": {"withPhoto": -1},
                }
            }
            data = await self._post_url(self.CONTENT_URL, "/content/v2/get/cards/list", payload)
            cards = data.get("cards", []) or []
            result.extend(cards)

            new_cursor = data.get("cursor", {})
            total = new_cursor.get("total", 0)
            if not cards or total < limit:
                break

            cursor = {
                "limit": limit,
                "updatedAt": new_cursor.get("updatedAt"),
                "nmID": new_cursor.get("nmID"),
            }

        return result

    # --------------------------------------------------------
    # Продажи (Statistics API)
    # --------------------------------------------------------

    async def list_sales_report(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        """Отчёт о реализации за период (reportDetailByPeriod, deprecated)."""
        result: list[dict[str, Any]] = []
        rrd_id = 0
        limit = 100_000

        date_from_str = date_from.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        date_to_str = date_to.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        while True:
            params = {
                "dateFrom": date_from_str,
                "dateTo": date_to_str,
                "limit": limit,
                "rrdid": rrd_id,
            }
            rows = await self._get_url(
                self.STATISTICS_URL,
                "/api/v5/supplier/reportDetailByPeriod",
                params=params,
            )

            if not isinstance(rows, list) or not rows:
                break

            result.extend(rows)

            last = rows[-1]
            new_rrd = last.get("rrd_id")
            if not new_rrd or len(rows) < limit:
                break
            rrd_id = int(new_rrd)

        return result

    # --------------------------------------------------------
    # Продажи (Finance API — новый)
    # --------------------------------------------------------

    async def list_sales_reports(
        self,
        date_from: date,
        date_to: date,
        period: str = "weekly",
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Список отчётов реализации (новый Finance API)."""
        payload: dict[str, Any] = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "period": period,
            "limit": min(limit, 1000),
            "offset": offset,
        }
        data = await self._post_url(
            self.FINANCE_URL,
            "/api/finance/v1/sales-reports/list",
            payload,
        )
        if not data:
            return []
        return data if isinstance(data, list) else []

    async def get_sales_report_detailed_by_period(
        self,
        date_from: date,
        date_to: date,
        period: str = "weekly",
        limit: int = 100_000,
        rrd_id: int = 0,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Детализация отчётов реализации за период (Finance API)."""
        result: list[dict[str, Any]] = []

        while True:
            payload: dict[str, Any] = {
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "period": period,
                "limit": min(limit, 100_000),
                "rrdId": rrd_id,
            }
            if fields:
                payload["fields"] = fields

            data = await self._post_url(
                self.FINANCE_URL,
                "/api/finance/v1/sales-reports/detailed",
                payload,
            )

            if not data:
                break

            rows = data if isinstance(data, list) else []
            if not rows:
                break

            result.extend(rows)

            last_rrd = rows[-1].get("rrdId")
            if not last_rrd or len(rows) < payload["limit"]:
                break
            rrd_id = int(last_rrd)

        return result
