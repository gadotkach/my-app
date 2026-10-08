"""Сервис синхронизации расходов Ozon Ads."""

import logging
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import AdvertisingExpense
from app.ozon_ads_client import OzonAdsClient, OzonAdsClientError

logger = logging.getLogger(__name__)


class SyncResult(TypedDict):
    created: int
    updated: int
    period_from: date
    period_to: date
    skipped: bool


async def sync_ozon_ads(
    user_id: int,
    client_id: str,
    client_secret: str,
    date_from: date,
    date_to: date,
) -> SyncResult:
    """Синхронизировать расходы Ozon Ads -> AdvertisingExpense."""
    result: SyncResult = {
        "created": 0,
        "updated": 0,
        "period_from": date_from,
        "period_to": date_to,
        "skipped": False,
    }

    async with OzonAdsClient(client_id, client_secret) as client:
        try:
            campaigns = await client.list_all_campaigns()
        except OzonAdsClientError as e:
            logger.warning("Ozon Ads: list_campaigns failed: %s", e)
            return result

        if not campaigns:
            logger.info("Ozon Ads: нет активных кампаний (user=%s)", user_id)
            result["skipped"] = True
            return result

        batches = [campaigns[i : i + 10] for i in range(0, len(campaigns), 10)]

        expenses_by_date: dict[date, Decimal] = {}

        for batch in batches:
            campaign_ids = [str(c["id"]) for c in batch if c.get("id")]
            if not campaign_ids:
                continue

            try:
                uuid = await client.create_statistics_report(
                    campaigns=campaign_ids,
                    date_from=date_from,
                    date_to=date_to,
                    group_by="DATE",
                )
                status = await client.wait_for_report(uuid, timeout_sec=60)
                if status.get("state") != "OK":
                    logger.warning("Ozon Ads: report not ready: %s", status)
                    continue

                csv_text = await client.download_report_csv(uuid)
                parsed = client.parse_csv_report(csv_text)

                for row in parsed:
                    d_str = row.get("date", "")
                    expense = row.get("expense", 0.0)
                    if not d_str or expense <= 0:
                        continue
                    try:
                        d = date.fromisoformat(d_str)
                    except ValueError:
                        continue
                    amount = Decimal(str(round(expense, 2)))
                    prev = expenses_by_date.get(d, Decimal("0"))
                    expenses_by_date[d] = prev + amount

            except OzonAdsClientError as e:
                logger.warning("Ozon Ads: report failed: %s", e)
                continue

    if not expenses_by_date:
        return result

    async with AsyncSessionLocal() as session:
        for d, amount in expenses_by_date.items():
            existing = await session.scalar(
                select(AdvertisingExpense).where(
                    AdvertisingExpense.user_id == user_id,
                    AdvertisingExpense.source == "ozon_ads",
                    AdvertisingExpense.date_from == d,
                    AdvertisingExpense.date_to == d,
                )
            )
            if existing is None:
                session.add(
                    AdvertisingExpense(
                        user_id=user_id,
                        source="ozon_ads",
                        date_from=d,
                        date_to=d,
                        amount=amount,
                        note="Автосинхронизация Ozon Ads",
                    )
                )
                result["created"] += 1
            else:
                existing.amount = amount
                result["updated"] += 1
        await session.commit()

    return result
