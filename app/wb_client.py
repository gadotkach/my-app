"""Клиент Wildberries Seller API."""

from datetime import UTC, date, datetime
from typing import Any

import httpx


class WBClientError(Exception):
    """Ошибка при обращении к Wildberries API."""


class WBClient:
    """Клиент WB API. Работает с Базовым, Сервисным и Персональным токенами."""

    COMMON_URL = "https://common-api.wildberries.ru"
    CONTENT_URL = "https://content-api.wildberries.ru"
    STATISTICS_URL = "https://statistics-api.wildberries.ru"
    FINANCE_URL = "https://finance-api.wildberries.ru"

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
            # WB Finance API возвращает 403, если:
            # 1. У продавца нет данных за период (нет продаж, нет отчётов).
            # 2. У токена нет прав на категорию «Финансы».
            # Различить нельзя — логируем и поднимаем ошибку, а вызывающий код
            # должен обработать её как «пусто» и не падать.
            raise WBClientError(
                "WB: 403 Forbidden — нет данных за период " "или нет прав на «Финансы»"
            )
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

    # --------------------------------------------------------
    # Продажи (Finance API — новый метод, работает с 29.01.2024)
    # --------------------------------------------------------

    async def list_sales_reports(
        self,
        date_from: date,
        date_to: date,
        period: str = "weekly",
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Список отчётов реализации (новый Finance API).

        Лимит: 1 запрос / 1 минуту. Персональный или Сервисный токен.
        Возвращает: [{"reportId": 123, "dateFrom": "...", "forPaySum": "...", ...}]
        """
        payload: dict[str, Any] = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "period": period,
            "limit": min(limit, 1000),
            "offset": offset,
        }
        data = await self._post(
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
        """
        Детализация отчётов реализации за период (новый Finance API).

        Лимит: 1 запрос / 1 минуту. Пагинация по rrdId — повторять до 204.
        """
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

            data = await self._post(
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
