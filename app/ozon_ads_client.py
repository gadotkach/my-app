"""Клиент Ozon Performance API (Ozon Ads).

Авторизация: client_id + client_secret -> access_token (живёт 30 мин).
Кеш токена — на уровне класса (per client_id).

Документация: https://docs.ozon.ru/api/performance/
"""

import asyncio
import csv
import io
import logging
import time
from datetime import date
from typing import Any

import httpx

from app.api_logger import log_request, log_response

logger = logging.getLogger(__name__)


class OzonAdsClientError(Exception):
    """Ошибка при обращении к Ozon Performance API."""


class OzonAdsClient:
    """Клиент Ozon Performance API.

    Хост: api-performance.ozon.ru
    Авторизация: client_id + client_secret -> Bearer token (30 мин).
    """

    BASE_URL = "https://api-performance.ozon.ru"

    # Кеш токенов: {client_id: (token, expires_at_epoch)}
    _token_cache: dict[str, tuple[str, float]] = {}

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        timeout: float = 30.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
            event_hooks={
                "request": [log_request],
                "response": [log_response],
            },
        )

    async def __aenter__(self) -> "OzonAdsClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    # --------------------------------------------------------
    # Авторизация
    # --------------------------------------------------------

    async def _get_token(self) -> str:
        """Получить access_token с кешированием (30 мин)."""
        cached = self._token_cache.get(self.client_id)
        if cached is not None:
            token, expires_at = cached
            if time.time() < expires_at - 60:
                return token

        response = await self._client.post(
            "/api/client/token",
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )

        if response.status_code == 401:
            raise OzonAdsClientError("Ozon Ads: неверный client_id или client_secret (401)")
        if response.status_code == 403:
            raise OzonAdsClientError("Ozon Ads: доступ запрещён (403) — проверьте права ключа")
        if response.status_code >= 400:
            raise OzonAdsClientError(
                f"Ozon Ads: ошибка авторизации {response.status_code}: " f"{response.text[:200]}"
            )

        data = response.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 1800))

        if not token:
            raise OzonAdsClientError("Ozon Ads: пустой access_token в ответе")

        self._token_cache[self.client_id] = (token, time.time() + expires_in)
        return token

    # --------------------------------------------------------
    # Общие обёртки
    # --------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = await self._get_token()
        response = await self._client.get(
            path,
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
        )
        return self._handle_response(response)

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        token = await self._get_token()
        response = await self._client.post(
            path,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        return self._handle_response(response)

    @staticmethod
    def _handle_response(response: httpx.Response) -> Any:
        if response.status_code == 401:
            raise OzonAdsClientError("Ozon Ads: не авторизован (401)")
        if response.status_code == 403:
            raise OzonAdsClientError("Ozon Ads: доступ запрещён (403)")
        if response.status_code == 404:
            raise OzonAdsClientError("Ozon Ads: не найдено (404)")
        if response.status_code == 429:
            raise OzonAdsClientError("Ozon Ads: превышен лимит запросов (429)")
        if response.status_code >= 400:
            raise OzonAdsClientError(
                f"Ozon Ads error {response.status_code}: {response.text[:200]}"
            )
        if not response.content:
            return {}
        return response.json()

    # --------------------------------------------------------
    # Кампании
    # --------------------------------------------------------

    async def list_campaigns(
        self,
        page: int = 1,
        page_size: int = 100,
        state: str = "CAMPAIGN_STATE_RUNNING",
    ) -> list[dict[str, Any]]:
        """Список кампаний. По умолчанию — только активные."""
        params: dict[str, Any] = {"page": page, "pageSize": page_size}
        if state:
            params["state"] = state
        data = await self._get("/api/client/campaign", params=params)
        return data.get("list", []) if isinstance(data, dict) else []

    async def list_all_campaigns(self) -> list[dict[str, Any]]:
        """Все активные кампании (со всех страниц)."""
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = await self.list_campaigns(page=page, page_size=100)
            if not batch:
                break
            result.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return result

    # --------------------------------------------------------
    # Статистика (отчёты)
    # --------------------------------------------------------

    async def create_statistics_report(
        self,
        campaigns: list[str],
        date_from: date,
        date_to: date,
        group_by: str = "DATE",
    ) -> str:
        """Создать задачу на отчёт. Возвращает UUID."""
        if not campaigns:
            raise OzonAdsClientError("Ozon Ads: список кампаний пуст")
        if len(campaigns) > 10:
            raise OzonAdsClientError("Ozon Ads: максимум 10 кампаний в одном отчёте")

        payload = {
            "campaigns": campaigns,
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "groupBy": group_by,
        }
        data = await self._post("/api/client/statistics", payload)
        uuid_raw = data.get("UUID") if isinstance(data, dict) else None
        if not uuid_raw:
            raise OzonAdsClientError("Ozon Ads: не получен UUID отчёта")
        return str(uuid_raw)

    async def get_report_status(self, uuid: str) -> dict[str, Any]:
        """Статус отчёта: NOT_STARTED / IN_PROGRESS / OK / ERROR."""
        data = await self._get(f"/api/client/statistics/{uuid}")
        return data if isinstance(data, dict) else {}

    async def wait_for_report(
        self,
        uuid: str,
        timeout_sec: int = 60,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Ждать готовности отчёта (polling каждые 3 секунды)."""
        started = time.time()
        while time.time() - started < timeout_sec:
            status = await self.get_report_status(uuid)
            state = status.get("state")
            if state == "OK":
                return status
            if state == "ERROR":
                raise OzonAdsClientError(
                    f"Ozon Ads: ошибка генерации отчёта: " f"{status.get('error', 'unknown')}"
                )
            await asyncio.sleep(poll_interval)
        raise OzonAdsClientError(f"Ozon Ads: таймаут ожидания отчёта ({timeout_sec} сек)")

    async def download_report_csv(self, uuid: str) -> str:
        """Скачать готовый отчёт (только одиночная кампания — CSV, не ZIP)."""
        token = await self._get_token()
        response = await self._client.get(
            "/api/client/statistics/report",
            headers={"Authorization": f"Bearer {token}"},
            params={"UUID": uuid},
        )

        if response.status_code >= 400:
            raise OzonAdsClientError(f"Ozon Ads: ошибка скачивания отчёта {response.status_code}")

        content_type = response.headers.get("content-type", "")
        if "zip" in content_type:
            raise OzonAdsClientError(
                "Ozon Ads: получен ZIP (несколько кампаний) — "
                "разбейте запрос на одиночные кампании"
            )
        return response.text

    @staticmethod
    def parse_csv_report(csv_text: str) -> list[dict[str, Any]]:
        """Парсинг CSV-отчёта Ozon Ads.

        Гибкий: ищет колонки по ключевым словам:
        - «Расход» -> expense
        - «Date» / «Дата» -> date
        - «Кампания» + «ID» -> campaign_id
        """
        reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
        result: list[dict[str, Any]] = []

        for row in reader:
            expense_raw: str | None = None
            date_raw: str | None = None
            campaign_raw: str | None = None

            for key, value in row.items():
                if key is None:
                    continue
                key_lower = key.lower().strip()
                if "расход" in key_lower:
                    expense_raw = value
                elif key_lower in ("date", "дата"):
                    date_raw = value
                elif "кампани" in key_lower and "id" in key_lower:
                    campaign_raw = value

            if expense_raw is None:
                continue

            try:
                expense_clean = (
                    expense_raw.replace(" ", "")
                    .replace(",", ".")
                    .replace("₽", "")
                    .replace("Р", "")
                    .strip()
                )
                expense = float(expense_clean) if expense_clean else 0.0
            except ValueError:
                continue

            result.append(
                {
                    "date": (date_raw or "").strip(),
                    "campaign_id": (campaign_raw or "").strip(),
                    "expense": expense,
                }
            )

        return result

    # --------------------------------------------------------
    # Проверка credentials
    # --------------------------------------------------------

    async def verify_credentials(self) -> bool:
        """True, если client_id + client_secret рабочие."""
        try:
            await self._get_token()
        except OzonAdsClientError:
            return False
        return True
