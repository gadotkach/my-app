from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import Marketplace, Product, Sale, User
from app.schemas import AnalyticsSummary, MarketplaceStats, ProductStats

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def summary(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalyticsSummary:
    stmt = select(
        func.count(Sale.id).label("sales_count"),
        func.coalesce(func.sum(Sale.price * Sale.quantity), 0).label("total_revenue"),
        func.coalesce(func.sum(Sale.commission), 0).label("total_commission"),
        func.coalesce(func.sum(Sale.logistics_cost), 0).label("total_logistics"),
    ).where(
        Sale.user_id == current_user.id,
        Sale.sold_at >= from_date,
        Sale.sold_at <= to_date,
    )
    row = (await session.execute(stmt)).one()
    revenue = Decimal(row.total_revenue)
    commission = Decimal(row.total_commission)
    logistics = Decimal(row.total_logistics)
    net_profit = revenue - commission - logistics

    return AnalyticsSummary(
        period_from=from_date,
        period_to=to_date,
        sales_count=row.sales_count,
        total_revenue=revenue,
        total_commission=commission,
        total_logistics=logistics,
        net_profit=net_profit,
    )


@router.get("/by-marketplace", response_model=list[MarketplaceStats])
async def by_marketplace(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MarketplaceStats]:
    stmt = (
        select(
            Marketplace.code,
            Marketplace.name,
            func.count(Sale.id).label("sales_count"),
            func.coalesce(func.sum(Sale.price * Sale.quantity), 0).label("total_revenue"),
            func.coalesce(func.sum(Sale.commission), 0).label("total_commission"),
            func.coalesce(func.sum(Sale.logistics_cost), 0).label("total_logistics"),
        )
        .join(Marketplace, Sale.marketplace_id == Marketplace.id)
        .where(
            Sale.user_id == current_user.id,
            Sale.sold_at >= from_date,
            Sale.sold_at <= to_date,
        )
        .group_by(Marketplace.id, Marketplace.code, Marketplace.name)
        .order_by(func.sum(Sale.price * Sale.quantity).desc())
    )
    rows = (await session.execute(stmt)).all()
    result: list[MarketplaceStats] = []
    for row in rows:
        revenue = Decimal(row.total_revenue)
        commission = Decimal(row.total_commission)
        logistics = Decimal(row.total_logistics)
        result.append(
            MarketplaceStats(
                marketplace_code=row.code,
                marketplace_name=row.name,
                sales_count=row.sales_count,
                total_revenue=revenue,
                total_commission=commission,
                total_logistics=logistics,
                net_profit=revenue - commission - logistics,
            )
        )
    return result


@router.get("/by-product", response_model=list[ProductStats])
async def by_product(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProductStats]:
    stmt = (
        select(
            Product.id,
            Product.name,
            func.count(Sale.id).label("sales_count"),
            func.coalesce(func.sum(Sale.price * Sale.quantity), 0).label("total_revenue"),
        )
        .join(Product, Sale.product_id == Product.id)
        .where(
            Sale.user_id == current_user.id,
            Sale.sold_at >= from_date,
            Sale.sold_at <= to_date,
        )
        .group_by(Product.id, Product.name)
        .order_by(func.sum(Sale.price * Sale.quantity).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        ProductStats(
            product_id=row.id,
            product_name=row.name,
            sales_count=row.sales_count,
            total_revenue=Decimal(row.total_revenue),
        )
        for row in rows
    ]
