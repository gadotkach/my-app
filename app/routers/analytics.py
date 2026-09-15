from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, require_active_subscription
from app.models import Marketplace, Product, Sale, TaxSettings, User
from app.schemas import (
    AnalyticsSummary,
    MarketplaceStats,
    ProductStats,
    ProfitByMarketplace,
    ProfitSummaryResponse,
    UnitEconomicsResponse,
)
from app.services.unit_economics import calculate_unit_economics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def summary(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
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
    current_user: User = Depends(require_active_subscription),
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
    current_user: User = Depends(require_active_subscription),
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


@router.get("/unit-economics", response_model=UnitEconomicsResponse)
async def unit_economics(
    product_id: int = Query(..., description="ID товара"),
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> UnitEconomicsResponse:
    """Юнит-экономика по одному товару за период."""
    # 1. Проверяем, что товар существует и принадлежит пользователю
    product_stmt = select(Product).where(
        Product.id == product_id,
        Product.user_id == current_user.id,
    )
    product = (await session.execute(product_stmt)).scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # 2. Берём налоговые настройки
    tax_stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    tax_settings = (await session.execute(tax_stmt)).scalar_one_or_none()

    # 3. Берём все продажи товара за период
    sales_stmt = select(Sale).where(
        Sale.user_id == current_user.id,
        Sale.product_id == product_id,
        Sale.sold_at >= from_date,
        Sale.sold_at <= to_date,
    )
    sales = (await session.execute(sales_stmt)).scalars().all()

    if not sales:
        # Нет продаж — возвращаем нули, но структура ответа та же
        return UnitEconomicsResponse(
            product_id=product.id,
            product_name=product.name,
            sku=product.sku,
            period_from=from_date,
            period_to=to_date,
            sales_count=0,
            quantity=0,
            gross_revenue=Decimal("0"),
            spp_amount=Decimal("0"),
            net_revenue=Decimal("0"),
            commission=Decimal("0"),
            logistics=Decimal("0"),
            return_logistics=Decimal("0"),
            acquiring=Decimal("0"),
            storage=Decimal("0"),
            marketplace_costs_total=Decimal("0"),
            payout=Decimal("0"),
            cogs=Decimal("0"),
            gross_profit=Decimal("0"),
            tax_amount=Decimal("0"),
            net_profit=Decimal("0"),
            margin_percent=Decimal("0"),
            roi_percent=Decimal("0"),
            profit_per_unit=Decimal("0"),
            warning="За выбранный период продаж не найдено",
        )

    # 4. Считаем юнит-экономику для каждой продажи
    results = [calculate_unit_economics(sale, product, tax_settings) for sale in sales]

    # 5. Суммируем
    total_gross = sum((r.gross_price * r.quantity for r in results), Decimal("0"))
    total_spp = sum((r.spp_amount * r.quantity for r in results), Decimal("0"))
    total_net = sum((r.net_price * r.quantity for r in results), Decimal("0"))
    total_commission = sum((r.commission * r.quantity for r in results), Decimal("0"))
    total_logistics = sum((r.logistics * r.quantity for r in results), Decimal("0"))
    total_return_logistics = sum((r.return_logistics * r.quantity for r in results), Decimal("0"))
    total_acquiring = sum((r.acquiring * r.quantity for r in results), Decimal("0"))
    total_storage = sum((r.storage * r.quantity for r in results), Decimal("0"))
    total_costs = sum((r.marketplace_costs_total * r.quantity for r in results), Decimal("0"))
    total_payout = sum((r.payout * r.quantity for r in results), Decimal("0"))
    total_cogs = sum((r.cogs for r in results), Decimal("0"))
    total_gross_profit = sum((r.gross_profit for r in results), Decimal("0"))
    total_tax = sum((r.tax_amount for r in results), Decimal("0"))
    total_net_profit = sum((r.net_profit for r in results), Decimal("0"))
    total_quantity = sum((r.quantity for r in results), 0)

    # 6. Метрики
    margin_percent = (
        (total_net_profit / total_net * Decimal("100")).quantize(Decimal("0.01"))
        if total_net > 0
        else Decimal("0")
    )
    roi_percent = (
        (total_net_profit / total_cogs * Decimal("100")).quantize(Decimal("0.01"))
        if total_cogs > 0
        else Decimal("0")
    )
    profit_per_unit = (
        (total_net_profit / total_quantity).quantize(Decimal("0.01"))
        if total_quantity > 0
        else Decimal("0")
    )

    # 7. Warning
    warning: str | None = None
    if total_net_profit < 0:
        warning = "Товар убыточен за выбранный период"

    return UnitEconomicsResponse(
        product_id=product.id,
        product_name=product.name,
        sku=product.sku,
        period_from=from_date,
        period_to=to_date,
        sales_count=len(sales),
        quantity=total_quantity,
        gross_revenue=total_gross,
        spp_amount=total_spp,
        net_revenue=total_net,
        commission=total_commission,
        logistics=total_logistics,
        return_logistics=total_return_logistics,
        acquiring=total_acquiring,
        storage=total_storage,
        marketplace_costs_total=total_costs,
        payout=total_payout,
        cogs=total_cogs,
        gross_profit=total_gross_profit,
        tax_amount=total_tax,
        net_profit=total_net_profit,
        margin_percent=margin_percent,
        roi_percent=roi_percent,
        profit_per_unit=profit_per_unit,
        warning=warning,
    )


@router.get("/profit", response_model=ProfitSummaryResponse)
async def profit(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> ProfitSummaryResponse:
    """Сводка прибыли за период с разбивкой по площадкам."""
    # 1. Все продажи за период
    sales_stmt = select(Sale).where(
        Sale.user_id == current_user.id,
        Sale.sold_at >= from_date,
        Sale.sold_at <= to_date,
    )
    sales = list((await session.execute(sales_stmt)).scalars().all())

    if not sales:
        return ProfitSummaryResponse(
            period_from=from_date,
            period_to=to_date,
            total_revenue=Decimal("0"),
            total_marketplace_costs=Decimal("0"),
            total_cogs=Decimal("0"),
            total_tax=Decimal("0"),
            total_net_profit=Decimal("0"),
            margin_percent=Decimal("0"),
            by_marketplace=[],
        )

    # 2. Товары для всех продаж — одним запросом (избегаем N+1)
    product_ids = {sale.product_id for sale in sales if sale.product_id is not None}
    products_map: dict[int, Product] = {}
    if product_ids:
        products_stmt = select(Product).where(Product.id.in_(product_ids))
        products = (await session.execute(products_stmt)).scalars().all()
        products_map = {p.id: p for p in products}

    # 3. Налоговые настройки
    tax_stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    tax_settings = (await session.execute(tax_stmt)).scalar_one_or_none()

    # 4. Группируем продажи по marketplace_id
    groups: dict[int, list[Sale]] = defaultdict(list)
    for sale in sales:
        groups[sale.marketplace_id].append(sale)

    # 5. Названия площадок — одним запросом
    marketplace_ids = list(groups.keys())
    mp_stmt = select(Marketplace).where(Marketplace.id.in_(marketplace_ids))
    marketplaces = (await session.execute(mp_stmt)).scalars().all()
    marketplace_map = {m.id: m for m in marketplaces}

    # 6. Считаем по каждой группе
    by_marketplace: list[ProfitByMarketplace] = []
    grand_revenue = Decimal("0")
    grand_costs = Decimal("0")
    grand_cogs = Decimal("0")
    grand_tax = Decimal("0")
    grand_profit = Decimal("0")

    for marketplace_id, marketplace_sales in groups.items():
        mp = marketplace_map[marketplace_id]

        # Считаем юнит-экономику для каждой продажи площадки
        results = [
            calculate_unit_economics(sale, products_map.get(sale.product_id or 0), tax_settings)
            for sale in marketplace_sales
        ]

        revenue = sum((r.net_price * r.quantity for r in results), Decimal("0"))
        costs = sum((r.marketplace_costs_total * r.quantity for r in results), Decimal("0"))
        cogs = sum((r.cogs for r in results), Decimal("0"))
        tax = sum((r.tax_amount for r in results), Decimal("0"))
        net_profit = sum((r.net_profit for r in results), Decimal("0"))

        margin = (
            (net_profit / revenue * Decimal("100")).quantize(Decimal("0.01"))
            if revenue > 0
            else Decimal("0")
        )

        by_marketplace.append(
            ProfitByMarketplace(
                marketplace_code=mp.code,
                marketplace_name=mp.name,
                sales_count=len(marketplace_sales),
                revenue=revenue,
                marketplace_costs=costs,
                cogs=cogs,
                tax_amount=tax,
                net_profit=net_profit,
                margin_percent=margin,
            )
        )

        grand_revenue += revenue
        grand_costs += costs
        grand_cogs += cogs
        grand_tax += tax
        grand_profit += net_profit

    # Сортируем по прибыли (по убыванию)
    by_marketplace.sort(key=lambda x: x.net_profit, reverse=True)

    total_margin = (
        (grand_profit / grand_revenue * Decimal("100")).quantize(Decimal("0.01"))
        if grand_revenue > 0
        else Decimal("0")
    )

    return ProfitSummaryResponse(
        period_from=from_date,
        period_to=to_date,
        total_revenue=grand_revenue,
        total_marketplace_costs=grand_costs,
        total_cogs=grand_cogs,
        total_tax=grand_tax,
        total_net_profit=grand_profit,
        margin_percent=total_margin,
        by_marketplace=by_marketplace,
    )
