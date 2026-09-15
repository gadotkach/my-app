"""Клиент Wildberries Seller API."""

from datetime import UTC, datetime
from typing import Any

import httpx


class WBClientError(Exception):
    """Ошибка при обращении к Wildberries API."""


class WBClient:
    """Клиент WB API. Работает с Базовым, Сервисным и Персональным токенами."""

    COMMON_URL = "https://common-api.wildberries.ru"
    CONTENT_URL = "https://content-api.wildberries.ru"
    STATISTICS_URL = "https://statistics-api.wildberries.ru"

    def __init__(self, api_token: str, timeout: float = 30.0):
        self.api_token = api_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        # ВАЖНО: WB не использует префикс Bearer
        return {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
        }

    async def _get(
        self,
        base_url: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            response = await client.get(path, headers=self._headers(), params=params or {})
        return self._handle_response(response)

    async def _post(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            response = await client.post(path, headers=self._headers(), json=payload)
        return self._handle_response(response)

    @staticmethod
    def _handle_response(response: httpx.Response) -> Any:
        if response.status_code == 401:
            raise WBClientError("WB: неверный токен (401 Unauthorized)")
        if response.status_code == 403:
            raise WBClientError("WB: доступ запрещён — проверьте права токена (403 Forbidden)")
        if response.status_code == 429:
            raise WBClientError(
                "WB: превышен лимит запросов (429 Too Many Requests). "
                "Для Базового токена лимит очень жёсткий"
            )
        if response.status_code >= 400:
            raise WBClientError(f"WB API error {response.status_code}: {response.text[:200]}")
        if not response.content:
            return {}
        return response.json()

    # --------------------------------------------------------
    # Проверка токена
    # --------------------------------------------------------

    async def ping(self) -> bool:
        """Проверка токена через /ping. True — токен рабочий."""
        try:
            data = await self._get(self.COMMON_URL, "/ping")
        except WBClientError:
            return False
        return bool(data.get("Status") == "OK" or "TS" in data)

    async def verify_credentials(self) -> bool:
        """Псевдоним для ping()."""
        return await self.ping()

    # --------------------------------------------------------
    # Товары (Content API)
    # --------------------------------------------------------

    async def list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Список карточек товаров продавца.

        Cursor-пагинация. Лимит — 100 карточек за запрос.
        Для Базового токена: 1 запрос в час.
        """
        result: list[dict[str, Any]] = []
        cursor: dict[str, Any] = {"limit": limit}

        while True:
            payload = {
                "settings": {
                    "cursor": cursor,
                    "filter": {"withPhoto": -1},
                }
            }
            data = await self._post(self.CONTENT_URL, "/content/v2/get/cards/list", payload)
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
        """
        Отчёт о реализации за период (reportDetailByPeriod).

        Пагинация — через параметр rrdid.
        Для Базового токена: 1 запрос раз в 3 часа.
        """
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
            rows = await self._get(
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
