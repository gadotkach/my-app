"""Тесты OzonAdsClient (unit, без HTTP)."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ozon_ads_client import OzonAdsClient, OzonAdsClientError


def _make_client() -> OzonAdsClient:
    return OzonAdsClient(client_id="cid", client_secret="csecret")


@pytest.mark.asyncio
async def test_get_token_caches() -> None:
    """Токен кешируется: второй вызов не идёт в HTTP."""
    client = _make_client()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "TOKEN",
        "expires_in": 1800,
        "token_type": "Bearer",
    }
    mock_response.content = b"x"  # непустой

    client._client = AsyncMock()
    client._client.post = AsyncMock(return_value=mock_response)

    # Очистить кеш на всякий случай
    OzonAdsClient._token_cache.clear()

    token1 = await client._get_token()
    token2 = await client._get_token()

    assert token1 == "TOKEN"
    assert token2 == "TOKEN"
    # POST /token вызван только один раз (второй — из кеша)
    assert client._client.post.call_count == 1


@pytest.mark.asyncio
async def test_get_token_401_raises() -> None:
    """401 → OzonAdsClientError."""
    client = _make_client()

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "unauthorized"

    client._client = AsyncMock()
    client._client.post = AsyncMock(return_value=mock_response)

    OzonAdsClient._token_cache.clear()

    with pytest.raises(OzonAdsClientError, match="401"):
        await client._get_token()


@pytest.mark.asyncio
async def test_create_statistics_report_no_campaigns() -> None:
    """Пустой список кампаний → ошибка."""
    client = _make_client()

    with pytest.raises(OzonAdsClientError, match="пуст"):
        await client.create_statistics_report(
            campaigns=[],
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 7),
        )


@pytest.mark.asyncio
async def test_create_statistics_report_too_many_campaigns() -> None:
    """Больше 10 кампаний → ошибка."""
    client = _make_client()

    with pytest.raises(OzonAdsClientError, match="максимум 10"):
        await client.create_statistics_report(
            campaigns=[str(i) for i in range(11)],
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 7),
        )


def test_parse_csv_report() -> None:
    """Парсинг CSV: извлекаем дату, ID кампании, расход."""
    # Формат Ozon Ads: заголовки + данные (разделитель ;)
    csv_text = (
        "Кампания ID; Дата; Расход, Р\n"
        "13883040; 2026-10-01; 1234,56\n"
        "13883040; 2026-10-02; 789,10\n"
    )

    parsed = OzonAdsClient.parse_csv_report(csv_text)
    assert len(parsed) == 2
    assert parsed[0]["date"] == "2026-10-01"
    assert parsed[0]["expense"] == 1234.56
    assert parsed[0]["campaign_id"] == "13883040"
    assert parsed[1]["date"] == "2026-10-02"
    assert parsed[1]["expense"] == 789.10
