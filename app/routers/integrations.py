from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.deps import get_current_user, get_session
from app.models import Marketplace, MarketplaceAccount, Product, Sale, User
from app.ozon_client import OzonClient, OzonClientError
from app.schemas import (
    MarketplaceAccountConnect,
    MarketplaceAccountRead,
    OzonSyncResult,
    OzonSyncSalesResult,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post(
    "/ozon/connect",
    response_model=MarketplaceAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_ozon(
    payload: MarketplaceAccountConnect,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MarketplaceAccountRead:
    if payload.marketplace_code != "ozon":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint supports only marketplace_code='ozon'",
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


@router.get("/accounts", response_model=list[MarketplaceAccountRead])
async def list_accounts(
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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

    api_key = decrypt(account.api_key_encrypted)
    since_iso = from_date.isoformat().replace("+00:00", "Z")
    to_iso = to_date.isoformat().replace("+00:00", "Z")

    try:
        async with OzonClient(account.client_id, api_key) as ozon:
            postings = await ozon.list_postings_for_range(since=since_iso, to=to_iso)
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
