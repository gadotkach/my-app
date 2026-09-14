import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.crypto import decrypt
from app.database import AsyncSessionLocal
from app.models import Marketplace, MarketplaceAccount, Product, Sale
from app.ozon_client import OzonClient, OzonClientError

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def sync_ozon_for_account(
    user_id: int,
    client_id: str,
    api_key: str,
    marketplace_id: int,
) -> dict[str, int]:
    """Синхронизирует товары и продажи для одного Ozon-аккаунта."""
    stats = {"products_created": 0, "products_updated": 0, "sales_created": 0, "sales_updated": 0}
    async with OzonClient(client_id, api_key) as ozon:
        # --- Товары ---
        try:
            ozon_products = await ozon.list_products()
            product_ids = [int(p["product_id"]) for p in ozon_products if "product_id" in p]
            details = await ozon.get_product_info(product_ids)
        except OzonClientError as e:
            logger.warning("Ozon products sync failed for user %s: %s", user_id, e)
            details = []

        async with AsyncSessionLocal() as session:
            for item in details:
                sku = str(item.get("sku") or item.get("offer_id") or item.get("id"))
                name = item.get("name") or "Unnamed"
                description = item.get("description") or None

                existing = await session.scalar(
                    select(Product).where(Product.user_id == user_id, Product.sku == sku)
                )
                if existing is None:
                    session.add(
                        Product(
                            user_id=user_id,
                            sku=sku,
                            name=name,
                            description=description,
                        )
                    )
                    stats["products_created"] += 1
                else:
                    existing.name = name
                    existing.description = description
                    stats["products_updated"] += 1
            await session.commit()

    # --- Продажи (за последние 7 дней) ---

    to = datetime.now(UTC)
    since = to - timedelta(days=7)
    try:
        async with OzonClient(client_id, api_key) as ozon:
            postings = await ozon.list_postings_for_range(
                since=since.isoformat().replace("+00:00", "Z"),
                to=to.isoformat().replace("+00:00", "Z"),
            )
    except OzonClientError as e:
        logger.warning("Ozon sales sync failed for user %s: %s", user_id, e)
        postings = []

    async with AsyncSessionLocal() as session:
        for posting in postings:
            external_id = str(posting.get("posting_number") or posting.get("order_id"))
            if not external_id:
                continue

            products = posting.get("products") or []
            total_price = Decimal("0")
            for p in products:
                price = p.get("price")
                quantity = int(p.get("quantity") or 1)
                if price is not None:
                    total_price += Decimal(str(price)) * quantity

            financial = (posting.get("financial_data") or {}).get("products") or []
            total_commission = Decimal("0")
            for fp in financial:
                commission = fp.get("commission_amount")
                if commission is not None:
                    total_commission += Decimal(str(commission))

            sold_at_raw = posting.get("in_process_at") or posting.get("created_at")
            if sold_at_raw:
                sold_at = datetime.fromisoformat(str(sold_at_raw).replace("Z", "+00:00"))
                if sold_at.tzinfo is None:
                    sold_at = sold_at.replace(tzinfo=UTC)
            else:
                sold_at = datetime.now(UTC)

            existing_sale = await session.scalar(
                select(Sale).where(
                    Sale.user_id == user_id,
                    Sale.marketplace_id == marketplace_id,
                    Sale.external_id == external_id,
                )
            )
            if existing_sale is None:
                session.add(
                    Sale(
                        user_id=user_id,
                        marketplace_id=marketplace_id,
                        product_id=None,
                        delivery_service_id=None,
                        external_id=external_id,
                        quantity=1,
                        price=total_price,
                        commission=total_commission,
                        logistics_cost=Decimal("0"),
                        sold_at=sold_at,
                    )
                )
                stats["sales_created"] += 1
            else:
                existing_sale.price = total_price
                existing_sale.commission = total_commission
                existing_sale.sold_at = sold_at
                stats["sales_updated"] += 1
        await session.commit()

    return stats


async def sync_all_accounts() -> None:
    """Задача планировщика: обходит все подключённые Ozon-аккаунты и синхронизирует."""
    logger.info("Starting scheduled Ozon sync")
    async with AsyncSessionLocal() as session:
        stmt = (
            select(MarketplaceAccount)
            .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
            .where(Marketplace.code == "ozon")
        )
        rows = (await session.execute(stmt)).all()

    total = {"products_created": 0, "products_updated": 0, "sales_created": 0, "sales_updated": 0}
    for (account,) in rows:
        try:
            api_key = decrypt(account.api_key_encrypted)
            stats = await sync_ozon_for_account(
                user_id=account.user_id,
                client_id=account.client_id,
                api_key=api_key,
                marketplace_id=account.marketplace_id,
            )
            logger.info("Synced Ozon account user_id=%s: %s", account.user_id, stats)
            for k in total:
                total[k] += stats[k]
        except Exception as e:
            logger.exception("Sync failed for user_id=%s: %s", account.user_id, e)

    logger.info("Scheduled sync done: %s", total)


def start_scheduler() -> None:
    """Запускает планировщик с интервалом 30 минут."""
    scheduler.add_job(
        sync_all_accounts,
        "interval",
        minutes=30,
        id="sync_all_accounts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (every 30 minutes)")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
