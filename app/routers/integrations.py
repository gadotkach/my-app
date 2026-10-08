from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.deps import get_session, require_active_subscription
from app.models import Marketplace, MarketplaceAccount, Product, Sale, User
from app.ozon_client import OzonClient, OzonClientError
from app.schemas import (
    MarketplaceAccountConnect,
    MarketplaceAccountRead,
    OzonSyncResult,
    OzonSyncSalesResult,
    WBSyncResult,
    WBSyncSalesResult,
)
from app.sync_service import trigger_sync_if_stale
from app.wb_client import WBClient, WBClientError

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post(
    "/ozon/connect",
    response_model=MarketplaceAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_ozon(
    payload: MarketplaceAccountConnect,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> MarketplaceAccountRead:
    if payload.marketplace_code != "ozon":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint supports only marketplace_code='ozon'",
        )

    if payload.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="client_id is required for Ozon",
        )

    marketplace = await session.scalar(
        select(Marketplace).where(Marketplace.code == payload.marketplace_code)
    )
    if marketplace is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Marketplace 'ozon' not found in database",
        )

    try:
        async with OzonClient(payload.client_id, payload.api_key) as ozon:
            await ozon.get_seller_info()
    except OzonClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    existing = await session.scalar(
        select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace_id == marketplace.id,
        )
    )

    if existing is not None:
        existing.client_id = payload.client_id
        existing.api_key_encrypted = encrypt(payload.api_key)
        await session.commit()
        await session.refresh(existing)
        account = existing
    else:
        account = MarketplaceAccount(
            user_id=current_user.id,
            marketplace_id=marketplace.id,
            client_id=payload.client_id,
            api_key_encrypted=encrypt(payload.api_key),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)

    return MarketplaceAccountRead(
        id=account.id,
        marketplace_code=marketplace.code,
        client_id=account.client_id,
        created_at=account.created_at,
    )


@router.post(
    "/wb/connect",
    response_model=MarketplaceAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_wb(
    payload: MarketplaceAccountConnect,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> MarketplaceAccountRead:
    marketplace = await session.scalar(select(Marketplace).where(Marketplace.code == "wildberries"))
    if marketplace is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Marketplace 'wb' not found in database",
        )

    # Проверка токена через WB /ping
    wb = WBClient(payload.api_key)
    if not await wb.ping():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WB: неверный токен (проверьте права и срок действия)",
        )

    existing = await session.scalar(
        select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace_id == marketplace.id,
        )
    )

    if existing is not None:
        existing.client_id = None
        existing.api_key_encrypted = encrypt(payload.api_key)
        await session.commit()
        await session.refresh(existing)
        account = existing
    else:
        account = MarketplaceAccount(
            user_id=current_user.id,
            marketplace_id=marketplace.id,
            client_id=None,
            api_key_encrypted=encrypt(payload.api_key),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)

    return MarketplaceAccountRead(
        id=account.id,
        marketplace_code=marketplace.code,
        client_id=account.client_id,
        created_at=account.created_at,
    )


@router.get("/accounts", response_model=list[MarketplaceAccountRead])
async def list_accounts(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> list[MarketplaceAccountRead]:
    stmt = (
        select(MarketplaceAccount, Marketplace.code)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(MarketplaceAccount.user_id == current_user.id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MarketplaceAccountRead(
            id=account.id,
            marketplace_code=code,
            client_id=account.client_id,
            created_at=account.created_at,
        )
        for account, code in rows
    ]


@router.post("/ozon/sync/products", response_model=OzonSyncResult)
async def sync_ozon_products(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> OzonSyncResult:
    account = await session.scalar(
        select(MarketplaceAccount)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(
            MarketplaceAccount.user_id == current_user.id,
            Marketplace.code == "ozon",
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ozon is not connected for this user",
        )

    if account.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ozon account is missing client_id",
        )

    api_key = decrypt(account.api_key_encrypted)
    try:
        async with OzonClient(account.client_id, api_key) as ozon:
            ozon_products = await ozon.list_products()
            product_ids = [int(p["product_id"]) for p in ozon_products if "product_id" in p]
            details = await ozon.get_product_info(product_ids)
    except OzonClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    created = 0
    updated = 0
    for item in details:
        sku = str(item.get("sku") or item.get("offer_id") or item.get("id"))
        name = item.get("name") or "Unnamed"
        description = item.get("description") or None

        existing = await session.scalar(
            select(Product).where(
                Product.user_id == current_user.id,
                Product.sku == sku,
            )
        )
        if existing is None:
            session.add(
                Product(
                    user_id=current_user.id,
                    sku=sku,
                    name=name,
                    description=description,
                )
            )
            created += 1
        else:
            existing.name = name
            existing.description = description
            updated += 1

    await session.commit()
    return OzonSyncResult(synced=len(details), created=created, updated=updated)


@router.post("/ozon/sync/sales", response_model=OzonSyncSalesResult)
async def sync_ozon_sales(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> OzonSyncSalesResult:
    account = await session.scalar(
        select(MarketplaceAccount)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(
            MarketplaceAccount.user_id == current_user.id,
            Marketplace.code == "ozon",
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ozon is not connected for this user",
        )

    if account.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ozon account is missing client_id",
        )

    api_key = decrypt(account.api_key_encrypted)
    since_iso = from_date.isoformat().replace("+00:00", "Z")
    to_iso = to_date.isoformat().replace("+00:00", "Z")

    try:
        async with OzonClient(account.client_id, api_key) as ozon:
            postings_fbs = await ozon.list_postings_for_range(since=since_iso, to=to_iso)
            postings_fbo = await ozon.list_fbo_postings_for_range(since=since_iso, to=to_iso)
            postings = postings_fbs + postings_fbo
    except OzonClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    marketplace = await session.scalar(select(Marketplace).where(Marketplace.code == "ozon"))
    if marketplace is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Marketplace 'ozon' not found",
        )

    created = 0
    updated = 0
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

        existing = await session.scalar(
            select(Sale).where(
                Sale.user_id == current_user.id,
                Sale.marketplace_id == marketplace.id,
                Sale.external_id == external_id,
            )
        )
        if existing is None:
            session.add(
                Sale(
                    user_id=current_user.id,
                    marketplace_id=marketplace.id,
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
            created += 1
        else:
            existing.price = total_price
            existing.commission = total_commission
            existing.sold_at = sold_at
            updated += 1

    await session.commit()
    return OzonSyncSalesResult(
        synced=len(postings),
        created=created,
        updated=updated,
        period_from=from_date,
        period_to=to_date,
    )


@router.post("/wb/sync/products", response_model=WBSyncResult)
async def sync_wb_products(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> WBSyncResult:
    account = await session.scalar(
        select(MarketplaceAccount)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(
            MarketplaceAccount.user_id == current_user.id,
            Marketplace.code == "wildberries",
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WB is not connected for this user",
        )

    api_key = decrypt(account.api_key_encrypted)
    wb = WBClient(api_key)
    try:
        cards = await wb.list_products()
    except WBClientError as e:
        err = str(e)
        if "403" in err or "Forbidden" in err:
            # Нет доступа / нет товаров — возвращаем пустой результат
            cards = []
        elif "429" in err or "limit" in err.lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="WB: превышен лимит запросов. Для Базового токена — 1 запрос/24ч, "
                "для Персонального/Сервисного — 1 запрос/мин. Попробуйте позже.",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    created = 0
    updated = 0
    for card in cards:
        nm_id = card.get("nmID")
        if nm_id is None:
            continue
        sku = str(nm_id)
        name = card.get("title") or card.get("subjectName") or f"WB-{nm_id}"
        description = card.get("description") or None

        # Габариты (WB отдаёт в см)
        dimensions = card.get("dimensions") or {}
        length = dimensions.get("length")
        width = dimensions.get("width")
        height = dimensions.get("height")

        existing = await session.scalar(
            select(Product).where(
                Product.user_id == current_user.id,
                Product.sku == sku,
            )
        )
        if existing is None:
            session.add(
                Product(
                    user_id=current_user.id,
                    sku=sku,
                    name=name,
                    description=description,
                    length_cm=Decimal(str(length)) if length is not None else None,
                    width_cm=Decimal(str(width)) if width is not None else None,
                    height_cm=Decimal(str(height)) if height is not None else None,
                )
            )
            created += 1
        else:
            existing.name = name
            existing.description = description
            if length is not None:
                existing.length_cm = Decimal(str(length))
            if width is not None:
                existing.width_cm = Decimal(str(width))
            if height is not None:
                existing.height_cm = Decimal(str(height))
            updated += 1

    await session.commit()
    return WBSyncResult(synced=len(cards), created=created, updated=updated)


@router.post("/wb/sync/sales", response_model=WBSyncSalesResult)
async def sync_wb_sales(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> WBSyncSalesResult:
    """Синхронизация продаж WB через новый Finance API."""
    account = await session.scalar(
        select(MarketplaceAccount)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(
            MarketplaceAccount.user_id == current_user.id,
            Marketplace.code == "wildberries",
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WB is not connected for this user",
        )

    marketplace = await session.scalar(select(Marketplace).where(Marketplace.code == "wildberries"))
    if marketplace is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Marketplace 'wb' not found",
        )

    api_key = decrypt(account.api_key_encrypted)
    wb = WBClient(api_key)

    try:
        rows = await wb.get_sales_report_detailed_by_period(
            date_from=from_date,
            date_to=to_date,
            period="daily",
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
    except WBClientError as e:
        err = str(e)
        if "403" in err or "Forbidden" in err:
            # Нет данных за период (нет продаж) — возвращаем пустой результат
            rows = []
        elif "429" in err or "limit" in err.lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="WB: превышен лимит запросов. Для Базового токена — 1 запрос/24ч, "
                "для Персонального/Сервисного — 1 запрос/мин. Попробуйте позже.",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    # Собираем nm_id
    nm_ids: set[str] = set()
    for row in rows:
        nm_id = row.get("nmId")
        if nm_id is not None:
            nm_ids.add(str(nm_id))

    products_map: dict[str, Product] = {}
    if nm_ids:
        products_stmt = select(Product).where(
            Product.user_id == current_user.id,
            Product.sku.in_(nm_ids),
        )
        products = (await session.execute(products_stmt)).scalars().all()
        products_map = {p.sku: p for p in products}

    def _d(row: dict[str, Any], key: str) -> Decimal:
        v = row.get(key)
        if v is None or v == "":
            return Decimal("0")
        return Decimal(str(v))

    def _d_opt(row: dict[str, Any], key: str) -> Decimal | None:
        v = row.get(key)
        if v is None or v == "":
            return None
        return Decimal(str(v))

    created = 0
    updated = 0
    for row in rows:
        rrd_id_val = row.get("rrdId")
        if rrd_id_val is None:
            continue
        external_id = str(rrd_id_val)

        doc_type = (row.get("docTypeName") or "").strip()
        if doc_type and doc_type.lower() != "продажа":
            continue

        nm_id = row.get("nmId")
        product = products_map.get(str(nm_id)) if nm_id is not None else None

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

        existing = await session.scalar(
            select(Sale).where(
                Sale.user_id == current_user.id,
                Sale.marketplace_id == marketplace.id,
                Sale.external_id == external_id,
            )
        )

        if existing is None:
            session.add(
                Sale(
                    user_id=current_user.id,
                    marketplace_id=marketplace.id,
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
            created += 1
        else:
            existing.quantity = quantity
            existing.price = price
            existing.commission = commission
            existing.commission_percent = commission_percent
            existing.logistics_cost = logistics_cost
            existing.return_logistics_cost = return_logistics_cost
            existing.acquiring_fee = acquiring_fee
            existing.acquiring_percent = acquiring_percent
            existing.storage_cost = storage_cost
            existing.spp_percent = spp_percent
            existing.spp_amount = spp_amount
            existing.retail_price_with_spp = retail_price_with_spp
            existing.payout_amount = payout_amount
            existing.sold_at = sold_at
            updated += 1

    await session.commit()
    return WBSyncSalesResult(
        synced=len(rows),
        created=created,
        updated=updated,
        period_from=datetime.combine(from_date, datetime.min.time()).replace(tzinfo=UTC),
        period_to=datetime.combine(to_date, datetime.max.time()).replace(tzinfo=UTC),
    )


@router.post("/sync-if-stale")
async def sync_if_stale(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[str]]:
    """
    Проверяет last_sync_at для всех аккаунтов пользователя.
    Для устаревших — запускает sync в фоне (не блокирует ответ).
    Возвращает: {"triggered": [...], "skipped": [...]}
    """
    return await trigger_sync_if_stale(current_user.id, session)
