import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.crypto import decrypt
from app.database import AsyncSessionLocal
from app.models import (
    Marketplace,
    MarketplaceAccount,
    OzonAdsAccount,
    Product,
    Sale,
    TaxSettings,
    TelegramSubscription,
)
from app.ozon_ads_client import OzonAdsClientError
from app.ozon_client import OzonClient, OzonClientError
from app.services.ozon_ads_sync import sync_ozon_ads
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

    # --- Продажи (Finance API — новый метод) ---
    # Лимит: 1 запрос / 1 минуту. Синкаем окно 3 дня.
    to_dt = datetime.now(UTC)
    since_dt = to_dt - timedelta(days=3)
    since_date = since_dt.date()
    to_date = to_dt.date()

    rows: list[dict[str, Any]] = []
    try:
        rows = await wb.get_sales_report_detailed_by_period(
            date_from=since_date,
            date_to=to_date,
            period="weekly",
            fields=[
                "rrdId",
                "srid",
                "nmId",
                "title",
                "vendorCode",
                "saleDt",
                "orderDt",
                "docTypeName",
                "quantity",
                "retailPrice",
                "retailPriceWithDisc",
                "retailAmount",
                "commissionPercent",
                "ppvzSalesCommission",
                "acquiringFee",
                "acquiringPercent",
                "deliveryService",
                "deliveryAmount",
                "paidStorage",
                "spp",
                "forPay",
            ],
        )
        if not rows:
            logger.info("WB sales: no data for period (user=%s)", user_id)
    except WBClientError as e:
        err = str(e)
        if "403" in err or "Forbidden" in err:
            # У продавца нет данных за период (нет продаж) — это не ошибка
            logger.info("WB sales: no data for period (403) for user=%s", user_id)
        elif "429" in err or "limit" in err.lower():
            logger.warning("WB sales sync rate limited for user %s: %s", user_id, e)
        else:
            logger.warning("WB sales sync failed for user %s: %s", user_id, e)
        rows = []

    # Собираем nm_id для маппинга
    nm_ids: set[str] = set()
    for row in rows:
        nm_id = row.get("nmId")
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
            rrd_id_val = row.get("rrdId")
            if rrd_id_val is None:
                continue
            external_id = str(rrd_id_val)

            doc_type = (row.get("docTypeName") or "").strip()
            if doc_type and doc_type.lower() != "продажа":
                logger.debug(
                    "WB row skipped (docType=%s, rrdId=%s, user=%s)",
                    doc_type,
                    external_id,
                    user_id,
                )
                continue

            nm_id = row.get("nmId")
            product = products_map.get(str(nm_id)) if nm_id is not None else None

            def _d(r: dict[str, Any], key: str) -> Decimal:
                v = r.get(key)
                if v is None or v == "":
                    return Decimal("0")
                return Decimal(str(v))

            def _d_opt(r: dict[str, Any], key: str) -> Decimal | None:
                v = r.get(key)
                if v is None or v == "":
                    return None
                return Decimal(str(v))

            quantity = int(row.get("quantity") or 1)
            price = _d(row, "retailAmount")
            commission = _d(row, "ppvzSalesCommission")
            commission_percent = _d_opt(row, "commissionPercent")
            logistics_cost = _d(row, "deliveryService")
            return_logistics_cost = _d(row, "deliveryAmount")
            acquiring_fee = _d(row, "acquiringFee")
            acquiring_percent = _d_opt(row, "acquiringPercent")
            storage_cost = _d(row, "paidStorage")
            spp_percent = _d_opt(row, "spp")
            retail_price_with_spp = _d_opt(row, "retailPriceWithDisc")
            payout_amount = _d(row, "forPay")

            spp_amount = (
                retail_price_with_spp * spp_percent / Decimal("100")
                if retail_price_with_spp is not None and spp_percent is not None
                else Decimal("0")
            )

            sold_at_raw = row.get("saleDt") or row.get("orderDt")
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
                        product_id=product.id if product is not None else None,
                        delivery_service_id=None,
                        external_id=external_id,
                        quantity=quantity,
                        price=price,
                        commission=commission,
                        commission_percent=commission_percent,
                        logistics_cost=logistics_cost,
                        return_logistics_cost=return_logistics_cost,
                        acquiring_fee=acquiring_fee,
                        acquiring_percent=acquiring_percent,
                        storage_cost=storage_cost,
                        spp_percent=spp_percent,
                        spp_amount=spp_amount,
                        retail_price_with_spp=retail_price_with_spp,
                        payout_amount=payout_amount,
                        sold_at=sold_at,
                    )
                )
                stats["sales_created"] += 1
            else:
                existing_sale.quantity = quantity
                existing_sale.price = price
                existing_sale.commission = commission
                existing_sale.commission_percent = commission_percent
                existing_sale.logistics_cost = logistics_cost
                existing_sale.return_logistics_cost = return_logistics_cost
                existing_sale.acquiring_fee = acquiring_fee
                existing_sale.acquiring_percent = acquiring_percent
                existing_sale.storage_cost = storage_cost
                existing_sale.spp_percent = spp_percent
                existing_sale.spp_amount = spp_amount
                existing_sale.retail_price_with_spp = retail_price_with_spp
                existing_sale.payout_amount = payout_amount
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


# ============================================================
# Ozon Ads (Performance API)
# ============================================================


async def sync_ozon_ads_all_accounts() -> None:
    """Задача планировщика: обходит все Ozon Ads-аккаунты. Запускается раз в 6 часов."""
    logger.info("Starting scheduled Ozon Ads sync")

    async with AsyncSessionLocal() as session:
        stmt = select(OzonAdsAccount)
        accounts = (await session.execute(stmt)).scalars().all()

    total_created = 0
    total_updated = 0

    for account in accounts:
        try:
            client_secret = decrypt(account.client_secret_encrypted)
            to_date = datetime.now(UTC).date()
            from_date = to_date - timedelta(days=7)

            stats = await sync_ozon_ads(
                user_id=account.user_id,
                client_id=account.client_id,
                client_secret=client_secret,
                date_from=from_date,
                date_to=to_date,
            )

            # Обновить last_sync_at
            async with AsyncSessionLocal() as session:
                acc = await session.get(OzonAdsAccount, account.id)
                if acc is not None:
                    acc.last_sync_at = datetime.now(UTC)
                    await session.commit()

            logger.info(
                "Synced Ozon Ads account user_id=%s: %s",
                account.user_id,
                stats,
            )
            total_created += stats.get("created", 0)
            total_updated += stats.get("updated", 0)

        except OzonAdsClientError as e:
            logger.warning(
                "Ozon Ads sync failed for user_id=%s: %s",
                account.user_id,
                e,
            )
        except Exception as e:
            logger.exception(
                "Ozon Ads sync unexpected error for user_id=%s: %s",
                account.user_id,
                e,
            )

    logger.info(
        "Scheduled Ozon Ads sync done: created=%s, updated=%s",
        total_created,
        total_updated,
    )


async def check_loss_making_products() -> None:
    """Раз в 6 часов: обходит подписчиков, проверяет убыточные товары за 7 дней.

    Отправляет уведомления через notify_loss_making для товаров с net_profit < 0.
    Учитывает notify_loss_making в TelegramSubscription.
    """
    from collections import defaultdict

    from app.services.telegram_notifier import notify_loss_making
    from app.services.unit_economics import calculate_unit_economics

    logger.info("Starting loss-making check")

    async with AsyncSessionLocal() as session:
        subs = (
            (
                await session.execute(
                    select(TelegramSubscription).where(
                        TelegramSubscription.notify_loss_making.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    if not subs:
        logger.info("No subscribers for loss-making notifications")
        return

    now = datetime.now(UTC)
    since = now - timedelta(days=7)

    sent = 0
    for sub in subs:
        try:
            async with AsyncSessionLocal() as session:
                # Продажи за 7 дней
                sales = list(
                    (
                        await session.execute(
                            select(Sale).where(
                                Sale.user_id == sub.user_id,
                                Sale.sold_at >= since,
                                Sale.sold_at <= now,
                                Sale.product_id.isnot(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if not sales:
                    continue

                # Товары
                product_ids = {s.product_id for s in sales if s.product_id}
                products = (
                    (await session.execute(select(Product).where(Product.id.in_(product_ids))))
                    .scalars()
                    .all()
                )
                products_map = {p.id: p for p in products}

                # Налоги
                tax_settings = (
                    await session.execute(
                        select(TaxSettings).where(TaxSettings.user_id == sub.user_id)
                    )
                ).scalar_one_or_none()

                # Группируем по product_id
                groups: dict[int, list[Sale]] = defaultdict(list)
                for s in sales:
                    if s.product_id:
                        groups[s.product_id].append(s)

                for product_id, product_sales in groups.items():
                    product = products_map.get(product_id)
                    if product is None:
                        continue

                    # Доля взносов на одну продажу
                    contrib_per_sale = (
                        (tax_settings.insurance_contributions / len(product_sales))
                        if tax_settings and tax_settings.insurance_contributions
                        else Decimal("0")
                    )

                    # Сумма net_profit за период
                    total_net = Decimal("0")
                    for s in product_sales:
                        ue = calculate_unit_economics(
                            sale=s,
                            product=product,
                            tax_settings=tax_settings,
                            contributions_per_sale=contrib_per_sale,
                        )
                        total_net += ue.net_profit

                    if total_net < 0:
                        try:
                            await notify_loss_making(
                                chat_id=sub.chat_id,
                                product_name=product.name or product.sku,
                                loss=float(abs(total_net)),
                            )
                            sent += 1
                        except Exception as e:
                            logger.warning(
                                "Failed to send loss notification to %s: %s",
                                sub.chat_id,
                                e,
                            )

        except Exception:
            logger.exception("Loss check failed for user_id=%s", sub.user_id)

    # Обновляем last_notification_at у всех, кому отправили
    if sent:
        async with AsyncSessionLocal() as session:
            for sub in subs:
                tg = await session.get(TelegramSubscription, sub.id)
                if tg is not None:
                    tg.last_notification_at = datetime.now(UTC)
            await session.commit()

    logger.info("Loss-making check done: %s notifications sent", sent)


async def send_daily_reports() -> None:
    """Раз в день в 9:00 МСК: ежедневный отчёт по выручке/прибыли/ДРР.

    Отправляет через notify_daily_report для подписчиков с notify_daily_report=True.
    """
    from app.services.telegram_notifier import notify_daily_report
    from app.services.unit_economics import calculate_unit_economics

    logger.info("Starting daily reports")

    async with AsyncSessionLocal() as session:
        subs = (
            (
                await session.execute(
                    select(TelegramSubscription).where(
                        TelegramSubscription.notify_daily_report.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    if not subs:
        logger.info("No subscribers for daily reports")
        return

    now = datetime.now(UTC)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday_start + timedelta(days=1)

    sent = 0
    for sub in subs:
        try:
            async with AsyncSessionLocal() as session:
                sales = list(
                    (
                        await session.execute(
                            select(Sale).where(
                                Sale.user_id == sub.user_id,
                                Sale.sold_at >= yesterday_start,
                                Sale.sold_at < yesterday_end,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                if not sales:
                    continue

                product_ids = {s.product_id for s in sales if s.product_id}
                products_map = {}
                if product_ids:
                    prods = (
                        (await session.execute(select(Product).where(Product.id.in_(product_ids))))
                        .scalars()
                        .all()
                    )
                    products_map = {p.id: p for p in prods}

                tax_settings = (
                    await session.execute(
                        select(TaxSettings).where(TaxSettings.user_id == sub.user_id)
                    )
                ).scalar_one_or_none()

                revenue = Decimal("0")
                profit = Decimal("0")
                orders = len(sales)

                for s in sales:
                    product = products_map.get(s.product_id) if s.product_id else None
                    ue = calculate_unit_economics(
                        sale=s,
                        product=product,
                        tax_settings=tax_settings,
                    )
                    revenue += ue.net_price
                    profit += ue.net_profit

                drr = 0.0  # упрощённо, без рекламы

                try:
                    await notify_daily_report(
                        chat_id=sub.chat_id,
                        summary={
                            "revenue": float(revenue),
                            "profit": float(profit),
                            "drr": drr,
                            "orders": orders,
                        },
                    )
                    sent += 1
                except Exception as e:
                    logger.warning("Failed to send daily report to %s: %s", sub.chat_id, e)
        except Exception:
            logger.exception("Daily report failed for user_id=%s", sub.user_id)

    logger.info("Daily reports done: %s sent", sent)


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
    scheduler.add_job(
        sync_ozon_ads_all_accounts,
        "interval",
        hours=6,  # раз в 6 часов
        id="sync_ozon_ads_all_accounts",
        replace_existing=True,
    )
    scheduler.add_job(
        check_loss_making_products,
        "interval",
        hours=6,  # раз в 6 часов
        id="check_loss_making_products",
        replace_existing=True,
    )
    scheduler.add_job(
        send_daily_reports,
        "cron",
        hour=6,  # 9:00 МСК = 6:00 UTC
        minute=0,
        id="send_daily_reports",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: Ozon 30min, WB 180min, Ozon Ads 6h, "
        "Loss check 6h, Daily reports 6:00 UTC"
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
