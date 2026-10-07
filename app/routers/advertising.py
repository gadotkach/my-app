"""Эндпоинты для рекламных расходов и ДРР (доля рекламных расходов)."""

from datetime import UTC, date, datetime
from datetime import time as _time
from decimal import Decimal
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, require_active_subscription
from app.models import AdvertisingExpense, Marketplace, Product, Sale, User
from app.schemas import (
    AdvertisingByMarketplace,
    AdvertisingBySource,
    AdvertisingExpenseCreate,
    AdvertisingExpenseRead,
    AdvertisingSummaryResponse,
)


class MarketplaceAgg(TypedDict):
    """Агрегация расходов по одной площадке."""

    code: str | None
    name: str | None
    amount: Decimal


router = APIRouter(prefix="/advertising", tags=["advertising"])

VALID_SOURCES = {
    "ozon_ads",
    "wb_adv",
    "yandex_direct",
    "vk_ads",
    "telegram_ads",
    "manual",
}


@router.post(
    "/expenses",
    response_model=AdvertisingExpenseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_expense(
    payload: AdvertisingExpenseCreate,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> AdvertisingExpenseRead:
    """Создать расход на рекламу."""
    if payload.source not in VALID_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"source must be one of {sorted(VALID_SOURCES)}",
        )
    if payload.date_to < payload.date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_to must be >= date_from",
        )
    if payload.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="amount must be > 0",
        )

    marketplace_id: int | None = None
    if payload.marketplace_code is not None:
        marketplace = await session.scalar(
            select(Marketplace).where(Marketplace.code == payload.marketplace_code)
        )
        if marketplace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Marketplace '{payload.marketplace_code}' not found",
            )
        marketplace_id = marketplace.id

    product_name: str | None = None
    if payload.product_id is not None:
        product = await session.scalar(
            select(Product).where(
                Product.id == payload.product_id,
                Product.user_id == current_user.id,
            )
        )
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )
        product_name = product.name

    expense = AdvertisingExpense(
        user_id=current_user.id,
        marketplace_id=marketplace_id,
        product_id=payload.product_id,
        source=payload.source,
        date_from=payload.date_from,
        date_to=payload.date_to,
        amount=payload.amount,
        note=payload.note,
    )
    session.add(expense)
    await session.commit()
    await session.refresh(expense)

    return AdvertisingExpenseRead(
        id=expense.id,
        marketplace_code=payload.marketplace_code,
        product_id=expense.product_id,
        product_name=product_name,
        source=expense.source,
        date_from=expense.date_from,
        date_to=expense.date_to,
        amount=expense.amount,
        note=expense.note,
        created_at=expense.created_at,
    )


@router.get("/expenses", response_model=list[AdvertisingExpenseRead])
async def list_expenses(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> list[AdvertisingExpenseRead]:
    """Список расходов за период."""
    stmt = (
        select(AdvertisingExpense, Marketplace.code, Product.name)
        .outerjoin(Marketplace, AdvertisingExpense.marketplace_id == Marketplace.id)
        .outerjoin(Product, AdvertisingExpense.product_id == Product.id)
        .where(
            AdvertisingExpense.user_id == current_user.id,
            AdvertisingExpense.date_from <= to_date,
            AdvertisingExpense.date_to >= from_date,
        )
        .order_by(AdvertisingExpense.date_from.desc(), AdvertisingExpense.id.desc())
    )
    rows = (await session.execute(stmt)).all()

    return [
        AdvertisingExpenseRead(
            id=exp.id,
            marketplace_code=mp_code,
            product_id=exp.product_id,
            product_name=prod_name,
            source=exp.source,
            date_from=exp.date_from,
            date_to=exp.date_to,
            amount=exp.amount,
            note=exp.note,
            created_at=exp.created_at,
        )
        for exp, mp_code, prod_name in rows
    ]


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: int,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Удалить расход."""
    expense = await session.get(AdvertisingExpense, expense_id)
    if expense is None or expense.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found",
        )
    await session.delete(expense)
    await session.commit()


@router.get("/summary", response_model=AdvertisingSummaryResponse)
async def summary(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> AdvertisingSummaryResponse:
    """Сводка расходов на рекламу за период + ДРР."""
    exp_stmt = (
        select(AdvertisingExpense, Marketplace.code, Marketplace.name)
        .outerjoin(Marketplace, AdvertisingExpense.marketplace_id == Marketplace.id)
        .where(
            AdvertisingExpense.user_id == current_user.id,
            AdvertisingExpense.date_from <= to_date,
            AdvertisingExpense.date_to >= from_date,
        )
    )
    exp_rows = (await session.execute(exp_stmt)).all()

    from_dt = datetime.combine(from_date, _time.min).replace(tzinfo=UTC)
    to_dt = datetime.combine(to_date, _time.max).replace(tzinfo=UTC)

    revenue_stmt = select(func.coalesce(func.sum(Sale.price * Sale.quantity), 0)).where(
        Sale.user_id == current_user.id,
        Sale.sold_at >= from_dt,
        Sale.sold_at <= to_dt,
    )
    total_revenue = Decimal((await session.scalar(revenue_stmt)) or 0)

    profit_stmt = select(
        func.coalesce(func.sum(Sale.price * Sale.quantity), 0)
        - func.coalesce(func.sum(Sale.commission), 0)
        - func.coalesce(func.sum(Sale.logistics_cost), 0)
    ).where(
        Sale.user_id == current_user.id,
        Sale.sold_at >= from_dt,
        Sale.sold_at <= to_dt,
    )
    net_profit_without_ads = Decimal((await session.scalar(profit_stmt)) or 0)

    total_advertising = sum((Decimal(exp.amount) for exp, _, _ in exp_rows), Decimal("0"))

    drr_percent = (
        (total_advertising / total_revenue * Decimal("100")).quantize(Decimal("0.01"))
        if total_revenue > 0
        else Decimal("0")
    )

    by_source_map: dict[str, Decimal] = {}
    by_marketplace_map: dict[str | None, MarketplaceAgg] = {}

    for exp, mp_code, mp_name in exp_rows:
        by_source_map[exp.source] = by_source_map.get(exp.source, Decimal("0")) + Decimal(
            exp.amount
        )
        key = mp_code
        if key not in by_marketplace_map:
            by_marketplace_map[key] = {
                "code": mp_code,
                "name": mp_name,
                "amount": Decimal("0"),
            }
        by_marketplace_map[key]["amount"] += Decimal(exp.amount)

    by_source = [
        AdvertisingBySource(
            source=src,
            amount=amt,
            drr_percent=(
                (amt / total_revenue * Decimal("100")).quantize(Decimal("0.01"))
                if total_revenue > 0
                else Decimal("0")
            ),
        )
        for src, amt in sorted(by_source_map.items(), key=lambda x: -x[1])
    ]

    by_marketplace = [
        AdvertisingByMarketplace(
            marketplace_code=info["code"],
            marketplace_name=info["name"],
            amount=info["amount"],
            drr_percent=(
                (info["amount"] / total_revenue * Decimal("100")).quantize(Decimal("0.01"))
                if total_revenue > 0
                else Decimal("0")
            ),
        )
        for info in sorted(by_marketplace_map.values(), key=lambda x: -x["amount"])
    ]

    return AdvertisingSummaryResponse(
        period_from=from_date,
        period_to=to_date,
        total_advertising_cost=total_advertising,
        total_revenue=total_revenue,
        drr_percent=drr_percent,
        net_profit_without_ads=net_profit_without_ads,
        net_profit_with_ads=net_profit_without_ads - total_advertising,
        by_source=by_source,
        by_marketplace=by_marketplace,
    )
