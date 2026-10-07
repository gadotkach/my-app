import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.crypto import decrypt
from app.database import AsyncSessionLocal
from app.models import Marketplace, MarketplaceAccount, Product, Sale
from app.ozon_client import OzonClient, OzonClientError
from app.wb_client import WBClient, WBClientError

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ============================================================
# Ozon
# ============================================================


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
            since_iso = since.isoformat().replace("+00:00", "Z")
            to_iso = to.isoformat().replace("+00:00", "Z")
            # FBS
            postings_fbs = await ozon.list_postings_for_range(
                since=since_iso,
                to=to_iso,
            )
            # FBO
            postings_fbo = await ozon.list_fbo_postings_for_range(
                since=since_iso,
                to=to_iso,
            )
            postings = postings_fbs + postings_fbo
            logger.info(
                "Ozon sync: FBS=%d, FBO=%d, total=%d",
                len(postings_fbs),
                len(postings_fbo),
                len(postings),
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


async def sync_ozon_all_accounts() -> None:
    """Задача планировщика: обходит все подключённые Ozon-аккаунты."""
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
            if account.client_id is None:
                logger.warning("Skipping Ozon account %s: client_id is None", account.id)
                continue
            api_key = decrypt(account.api_key_encrypted)
            stats = await sync_ozon_for_account(
                user_id=account.user_id,
                client_id=account.client_id,
                api_key=api_key,
                marketplace_id=account.marketplace_id,
            )
            # Обновляем last_sync_at
            async with AsyncSessionLocal() as s:
                acc = await s.scalar(
                    select(MarketplaceAccount).where(MarketplaceAccount.id == account.id)
                )
                if acc is not None:
                    acc.last_sync_at = datetime.now(UTC)
                    await s.commit()
            logger.info("Synced Ozon account user_id=%s: %s", account.user_id, stats)
            for k in total:
                total[k] += stats[k]
        except Exception as e:
            logger.exception("Ozon sync failed for user_id=%s: %s", account.user_id, e)

    logger.info("Scheduled Ozon sync done: %s", total)


# ============================================================
# Wildberries
# ============================================================


async def sync_wb_for_account(
    user_id: int,
    api_key: str,
    marketplace_id: int,
) -> dict[str, int]:
    """
    Синхронизирует товары и продажи для одного WB-аккаунта.

    ВАЖНО: WB Базовый токен имеет очень жёсткие лимиты —
    list_products: 1 запрос/час, list_sales_report: 1 запрос/3 часа.
    Поэтому этот job запускается раз в 3 часа.
    """
    stats = {"products_created": 0, "products_updated": 0, "sales_created": 0, "sales_updated": 0}
    wb = WBClient(api_key)

    # --- Товары ---
    try:
        cards = await wb.list_products()
    except WBClientError as e:
        # 429 — rate limit, не ретраим
        if "429" in str(e) or "limit" in str(e).lower():
            logger.warning("WB products sync rate limited for user %s: %s", user_id, e)
        else:
            logger.warning("WB products sync failed for user %s: %s", user_id, e)
        cards = []

    async with AsyncSessionLocal() as session:
        for card in cards:
            nm_id = card.get("nmID")
            if nm_id is None:
                continue
            sku = str(nm_id)
            name = card.get("title") or card.get("subjectName") or f"WB-{nm_id}"
            description = card.get("description") or None

            dimensions = card.get("dimensions") or {}
            length = dimensions.get("length")
            width = dimensions.get("width")
            height = dimensions.get("height")

            existing_product = await session.scalar(
                select(Product).where(Product.user_id == user_id, Product.sku == sku)
            )
            if existing_product is None:
                session.add(
                    Product(
                        user_id=user_id,
                        sku=sku,
                        name=name,
                        description=description,
                        length_cm=Decimal(str(length)) if length is not None else None,
                        width_cm=Decimal(str(width)) if width is not None else None,
                        height_cm=Decimal(str(height)) if height is not None else None,
                    )
                )
                stats["products_created"] += 1
            else:
                existing_product.name = name
                existing_product.description = description
                if length is not None:
                    existing_product.length_cm = Decimal(str(length))
                if width is not None:
                    existing_product.width_cm = Decimal(str(width))
                if height is not None:
                    existing_product.height_cm = Decimal(str(height))
                stats["products_updated"] += 1
        await session.commit()

    # --- Продажи (за последние 3 дня, чтобы не пересекаться с интервалом) ---
    to = datetime.now(UTC)
    since = to - timedelta(days=3)
    try:
        rows = await wb.list_sales_report(date_from=since, date_to=to)
    except WBClientError as e:
        if "429" in str(e) or "limit" in str(e).lower():
            logger.warning("WB sales sync rate limited for user %s: %s", user_id, e)
        else:
            logger.warning("WB sales sync failed for user %s: %s", user_id, e)
        rows = []

    # Собираем nm_id для маппинга
    nm_ids: set[str] = set()
    for row in rows:
        nm_id = row.get("nm_id")
        if nm_id is not None:
            nm_ids.add(str(nm_id))

    async with AsyncSessionLocal() as session:
        products_map: dict[str, Product] = {}
        if nm_ids:
            products_stmt = select(Product).where(
                Product.user_id == user_id,
                Product.sku.in_(nm_ids),
            )
            products = (await session.execute(products_stmt)).scalars().all()
            products_map = {p.sku: p for p in products}

        for row in rows:
            srid = row.get("srid")
            if not srid:
                continue
            external_id = str(srid)

            nm_id = row.get("nm_id")
            product = products_map.get(str(nm_id)) if nm_id is not None else None

            ppvz_for_pay = Decimal(str(row.get("ppvz_for_pay") or "0"))
            ppvz_sales_commission = Decimal(str(row.get("ppvz_sales_commission") or "0"))
            acquiring_fee = Decimal(str(row.get("acquiring_fee") or "0"))
            delivery_rub = Decimal(str(row.get("delivery_rub") or "0"))
            storage_fee = Decimal(str(row.get("storage_fee") or "0"))
            retail_price_with_spp = row.get("retail_price_withdisc_rub")
            spp_percent = row.get("ppvz_spp_prc")

            price = ppvz_for_pay + ppvz_sales_commission + acquiring_fee + delivery_rub
            quantity = int(row.get("ppvz_vw") or 1)

            sold_at_raw = row.get("sale_dt") or row.get("order_dt") or row.get("rr_dt")
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

            spp_amount = (
                Decimal(str(retail_price_with_spp)) * Decimal(str(spp_percent)) / Decimal("100")
                if retail_price_with_spp is not None and spp_percent is not None
                else Decimal("0")
            )

            if existing_sale is None:
                session.add(
                    Sale(
                        user_id=user_id,
                        marketplace_id=marketplace_id,
                        product_id=product.id if product is not None else None,
                        delivery_service_id=None,
                        external_id=external_id,
                        quantity=quantity,
                        price=price,
                        commission=ppvz_sales_commission,
                        logistics_cost=delivery_rub,
                        acquiring_fee=acquiring_fee,
                        storage_cost=storage_fee,
                        spp_percent=Decimal(str(spp_percent)) if spp_percent is not None else None,
                        spp_amount=spp_amount,
                        retail_price_with_spp=(
                            Decimal(str(retail_price_with_spp))
                            if retail_price_with_spp is not None
                            else None
                        ),
                        payout_amount=ppvz_for_pay,
                        sold_at=sold_at,
                    )
                )
                stats["sales_created"] += 1
            else:
                existing_sale.quantity = quantity
                existing_sale.price = price
                existing_sale.commission = ppvz_sales_commission
                existing_sale.logistics_cost = delivery_rub
                existing_sale.acquiring_fee = acquiring_fee
                existing_sale.storage_cost = storage_fee
                existing_sale.spp_percent = (
                    Decimal(str(spp_percent)) if spp_percent is not None else None
                )
                existing_sale.spp_amount = spp_amount
                existing_sale.retail_price_with_spp = (
                    Decimal(str(retail_price_with_spp))
                    if retail_price_with_spp is not None
                    else None
                )
                existing_sale.payout_amount = ppvz_for_pay
                existing_sale.sold_at = sold_at
                stats["sales_updated"] += 1
        await session.commit()

    return stats


async def sync_wb_all_accounts() -> None:
    """Задача планировщика: обходит все WB-аккаунты. Запускается раз в 3 часа."""
    logger.info("Starting scheduled WB sync")
    async with AsyncSessionLocal() as session:
        stmt = (
            select(MarketplaceAccount)
            .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
            .where(Marketplace.code == "wildberries")
        )
        rows = (await session.execute(stmt)).all()

    total = {"products_created": 0, "products_updated": 0, "sales_created": 0, "sales_updated": 0}
    for (account,) in rows:
        try:
            api_key = decrypt(account.api_key_encrypted)
            stats = await sync_wb_for_account(
                user_id=account.user_id,
                api_key=api_key,
                marketplace_id=account.marketplace_id,
            )
            # Обновляем last_sync_at
            async with AsyncSessionLocal() as s:
                acc = await s.scalar(
                    select(MarketplaceAccount).where(MarketplaceAccount.id == account.id)
                )
                if acc is not None:
                    acc.last_sync_at = datetime.now(UTC)
                    await s.commit()
            logger.info("Synced WB account user_id=%s: %s", account.user_id, stats)
            for k in total:
                total[k] += stats[k]
        except Exception as e:
            logger.exception("WB sync failed for user_id=%s: %s", account.user_id, e)

    logger.info("Scheduled WB sync done: %s", total)


# ============================================================
# Lifecycle
# ============================================================


def start_scheduler() -> None:
    """
    Запускает два job'а:
    - Ozon: каждые 30 минут (Ozon API терпит частые запросы)
    - WB: каждые 3 часа (WB Базовый токен — 1 запрос/3 часа)
    """
    scheduler.add_job(
        sync_ozon_all_accounts,
        "interval",
        minutes=30,
        id="sync_ozon_all_accounts",
        replace_existing=True,
    )
    scheduler.add_job(
        sync_wb_all_accounts,
        "interval",
        minutes=180,  # 3 часа
        id="sync_wb_all_accounts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: Ozon every 30 min, WB every 180 min")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
