from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, require_active_subscription
from app.models import Marketplace, Product, Sale, TaxSettings, User
from app.schemas import (
    ABCAnalysisResponse,
    ABCGroupStats,
    ABCProductItem,
    AnalyticsSummary,
    CalculatorRequest,
    CalculatorResponse,
    MarketplaceStats,
    ProductStats,
    ProfitByMarketplace,
    ProfitSummaryResponse,
    UnitEconomicsAllResponse,
    UnitEconomicsProductItem,
    UnitEconomicsResponse,
)
from app.services.unit_economics import (
    calculate_economics_from_params,
    calculate_recommended_price,
    calculate_unit_economics,
)


def _prorated_contributions_per_sale(
    tax_settings: "TaxSettings | None",
    num_sales: int,
    period_days: int,
) -> Decimal:
    """
    Считает долю пропорциональных страховых взносов, приходящуюся на одну продажу.

    Логика:
    - Взносы применяются только для УСН «Доходы» (USN_INCOME).
    - Годовая сумма взносов распределяется по периоду: insurance * period_days / 365.
    - Затем делится на количество продаж, чтобы при суммировании по периоду
      получить ровно правильную сумму.

    Для НПД / УСН Д-Р / ПСН — возвращает 0.
    """
    from decimal import Decimal as _D

    if tax_settings is None:
        return _D("0")
    if getattr(tax_settings, "tax_system", None) != "USN_INCOME":
        return _D("0")
    if num_sales <= 0:
        return _D("0")

    insurance = _D(str(tax_settings.insurance_contributions or 0))
    prorated = insurance * _D(str(period_days)) / _D("365")
    return (prorated / _D(str(num_sales))).quantize(_D("0.01"))


class AdvertisingDistribution(TypedDict):
    """Результат распределения рекламных расходов."""

    total: Decimal
    by_product: dict[int, Decimal]
    by_marketplace: dict[int, Decimal]


router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _distribute_advertising_cost(
    session: "AsyncSession",
    user_id: int,
    from_date: datetime,
    to_date: datetime,
) -> AdvertisingDistribution:
    """
    Собирает расходы на рекламу за период и распределяет их:
    - по товарам (product_id)
    - по площадкам (marketplace_id)
    - общая сумма

    Логика:
    - Если расход привязан к товару → только этому товару.
    - Если привязан к площадке (без товара) → распределяется между товарами
      этой площадки пропорционально выручке.
    - Без привязки → распределяется по всем товарам пропорционально выручке.
    """
    from app.models import AdvertisingExpense

    # 1. Забираем все расходы за период
    exp_stmt = select(AdvertisingExpense).where(
        AdvertisingExpense.user_id == user_id,
        AdvertisingExpense.date_from <= to_date.date(),
        AdvertisingExpense.date_to >= from_date.date(),
    )
    expenses = list((await session.execute(exp_stmt)).scalars().all())

    total_advertising = sum((Decimal(e.amount) for e in expenses), Decimal("0"))

    result: AdvertisingDistribution = {
        "total": total_advertising,
        "by_product": {},
        "by_marketplace": {},
    }

    if not expenses:
        return result

    # 2. Выручка по товарам и по площадкам за период (для распределения)
    sales_stmt = (
        select(
            Sale.product_id,
            Sale.marketplace_id,
            func.coalesce(func.sum(Sale.price * Sale.quantity), 0).label("revenue"),
        )
        .where(
            Sale.user_id == user_id,
            Sale.sold_at >= from_date,
            Sale.sold_at <= to_date,
            Sale.product_id.isnot(None),
        )
        .group_by(Sale.product_id, Sale.marketplace_id)
    )
    rows = (await session.execute(sales_stmt)).all()

    product_revenue: dict[int, Decimal] = {}
    marketplace_revenue: dict[int, Decimal] = {}
    for r in rows:
        pid = r.product_id
        mid = r.marketplace_id
        rev = Decimal(r.revenue or 0)
        if pid is not None:
            product_revenue[pid] = product_revenue.get(pid, Decimal("0")) + rev
        if mid is not None:
            marketplace_revenue[mid] = marketplace_revenue.get(mid, Decimal("0")) + rev

    total_revenue = sum(product_revenue.values(), Decimal("0"))

    # 3. Распределяем каждый расход
    for e in expenses:
        amount = Decimal(e.amount)

        if e.product_id is not None:
            # На конкретный товар
            result["by_product"][e.product_id] = (
                result["by_product"].get(e.product_id, Decimal("0")) + amount
            )
            if e.marketplace_id is not None:
                result["by_marketplace"][e.marketplace_id] = (
                    result["by_marketplace"].get(e.marketplace_id, Decimal("0")) + amount
                )

        elif e.marketplace_id is not None:
            # На площадку → распределяем по товарам этой площадки
            result["by_marketplace"][e.marketplace_id] = (
                result["by_marketplace"].get(e.marketplace_id, Decimal("0")) + amount
            )
            # Найти товары этой площадки
            mp_revenue = Decimal("0")
            mp_products: dict[int, Decimal] = {}
            for r in rows:
                if r.marketplace_id == e.marketplace_id and r.product_id is not None:
                    rev = Decimal(r.revenue or 0)
                    mp_products[r.product_id] = mp_products.get(r.product_id, Decimal("0")) + rev
                    mp_revenue += rev

            if mp_revenue > 0:
                for pid, rev in mp_products.items():
                    share = amount * rev / mp_revenue
                    result["by_product"][pid] = result["by_product"].get(pid, Decimal("0")) + share

        else:
            # Без привязки → по всем товарам пропорционально выручке
            if total_revenue > 0:
                for pid, rev in product_revenue.items():
                    share = amount * rev / total_revenue
                    result["by_product"][pid] = result["by_product"].get(pid, Decimal("0")) + share
            # И по площадкам — пропорционально выручке площадки
            for mid, rev in marketplace_revenue.items():
                share = amount * rev / total_revenue if total_revenue > 0 else Decimal("0")
                result["by_marketplace"][mid] = (
                    result["by_marketplace"].get(mid, Decimal("0")) + share
                )

    return result


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

    # Реклама / ДРР
    adv = await _distribute_advertising_cost(session, current_user.id, from_date, to_date)
    advertising_cost = adv["total"]
    drr_percent = (
        (advertising_cost / revenue * Decimal("100")).quantize(Decimal("0.01"))
        if revenue > 0
        else Decimal("0")
    )
    net_profit_with_ads = net_profit - advertising_cost

    return AnalyticsSummary(
        period_from=from_date,
        period_to=to_date,
        sales_count=row.sales_count,
        total_revenue=revenue,
        total_commission=commission,
        total_logistics=logistics,
        net_profit=net_profit,
        advertising_cost=advertising_cost,
        drr_percent=drr_percent,
        net_profit_with_ads=net_profit_with_ads,
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


@router.get("/unit-economics/all", response_model=UnitEconomicsAllResponse)
async def unit_economics_all(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> UnitEconomicsAllResponse:
    """
    Юнит-экономика по всем товарам пользователя за период.
    Возвращает таблицу: товар + метрики + флаг убыточности.
    Используется на странице /unit-economics.
    """
    # 1. Все продажи за период с привязкой к товару
    sales_stmt = select(Sale).where(
        Sale.user_id == current_user.id,
        Sale.sold_at >= from_date,
        Sale.sold_at <= to_date,
        Sale.product_id.isnot(None),
    )
    sales = list((await session.execute(sales_stmt)).scalars().all())

    if not sales:
        return UnitEconomicsAllResponse(
            period_from=from_date,
            period_to=to_date,
            total_sales_count=0,
            total_quantity=0,
            total_gross_revenue=Decimal("0"),
            total_net_revenue=Decimal("0"),
            total_commission=Decimal("0"),
            total_logistics=Decimal("0"),
            total_acquiring=Decimal("0"),
            total_storage=Decimal("0"),
            total_marketplace_costs=Decimal("0"),
            total_cogs=Decimal("0"),
            total_tax=Decimal("0"),
            total_net_profit=Decimal("0"),
            total_advertising_cost=Decimal("0"),
            drr_percent=Decimal("0"),
            total_net_profit_with_ads=Decimal("0"),
            products=[],
        )

    # 2. Все товары — одним запросом
    product_ids = {sale.product_id for sale in sales if sale.product_id is not None}
    products_stmt = select(Product).where(Product.id.in_(product_ids))
    products = (await session.execute(products_stmt)).scalars().all()
    products_map = {p.id: p for p in products}

    # 3. Налоговые настройки
    tax_stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    tax_settings = (await session.execute(tax_stmt)).scalar_one_or_none()
    period_days = max(1, (to_date - from_date).days)

    # 4. Группируем продажи по product_id
    groups: dict[int, list[Sale]] = defaultdict(list)
    for sale in sales:
        if sale.product_id is None:
            continue
        groups[sale.product_id].append(sale)

    # 4.5. Реклама / ДРР — распределение по товарам
    adv = await _distribute_advertising_cost(session, current_user.id, from_date, to_date)
    adv_by_product: dict[int, Decimal] = adv["by_product"]
    total_advertising_cost = adv["total"]

    # 5. Считаем метрики по каждому товару
    items: list[UnitEconomicsProductItem] = []

    grand_sales_count = 0
    grand_quantity = 0
    grand_gross = Decimal("0")
    grand_net = Decimal("0")
    grand_commission = Decimal("0")
    grand_logistics = Decimal("0")
    grand_acquiring = Decimal("0")
    grand_storage = Decimal("0")
    grand_costs = Decimal("0")
    grand_cogs = Decimal("0")
    grand_tax = Decimal("0")
    grand_profit = Decimal("0")

    for product_id, product_sales in groups.items():
        product = products_map.get(product_id)
        if product is None:
            continue

        contributions_per_sale = _prorated_contributions_per_sale(
            tax_settings, len(product_sales), period_days
        )
        results = [
            calculate_unit_economics(s, product, tax_settings, contributions_per_sale)
            for s in product_sales
        ]

        gross = sum((r.gross_price * r.quantity for r in results), Decimal("0"))
        net = sum((r.net_price * r.quantity for r in results), Decimal("0"))
        commission = sum((r.commission * r.quantity for r in results), Decimal("0"))
        logistics = sum((r.logistics * r.quantity for r in results), Decimal("0"))
        acquiring = sum((r.acquiring * r.quantity for r in results), Decimal("0"))
        storage = sum((r.storage * r.quantity for r in results), Decimal("0"))
        costs = sum((r.marketplace_costs_total * r.quantity for r in results), Decimal("0"))
        cogs = sum((r.cogs for r in results), Decimal("0"))
        tax = sum((r.tax_amount for r in results), Decimal("0"))
        net_profit = sum((r.net_profit for r in results), Decimal("0"))
        quantity = sum((r.quantity for r in results), 0)

        margin = (
            (net_profit / net * Decimal("100")).quantize(Decimal("0.01"))
            if net > 0
            else Decimal("0")
        )
        roi = (
            (net_profit / cogs * Decimal("100")).quantize(Decimal("0.01"))
            if cogs > 0
            else Decimal("0")
        )
        per_unit = (
            (net_profit / quantity).quantize(Decimal("0.01")) if quantity > 0 else Decimal("0")
        )

        # Реклама / ДРР для товара
        adv_cost = adv_by_product.get(product.id, Decimal("0")).quantize(Decimal("0.01"))
        drr_product = (
            (adv_cost / net * Decimal("100")).quantize(Decimal("0.01")) if net > 0 else Decimal("0")
        )
        profit_with_ads = (net_profit - adv_cost).quantize(Decimal("0.01"))

        items.append(
            UnitEconomicsProductItem(
                product_id=product.id,
                product_name=product.name,
                sku=product.sku,
                sales_count=len(product_sales),
                quantity=quantity,
                gross_revenue=gross,
                net_revenue=net,
                commission=commission,
                logistics=logistics,
                acquiring=acquiring,
                storage=storage,
                marketplace_costs_total=costs,
                cogs=cogs,
                tax_amount=tax,
                net_profit=net_profit,
                advertising_cost=adv_cost,
                drr_percent=drr_product,
                net_profit_with_ads=profit_with_ads,
                margin_percent=margin,
                roi_percent=roi,
                profit_per_unit=per_unit,
                is_loss=profit_with_ads < 0,
            )
        )

        grand_sales_count += len(product_sales)
        grand_quantity += quantity
        grand_gross += gross
        grand_net += net
        grand_commission += commission
        grand_logistics += logistics
        grand_acquiring += acquiring
        grand_storage += storage
        grand_costs += costs
        grand_cogs += cogs
        grand_tax += tax
        grand_profit += net_profit

    # Сортируем по прибыли (убывание)
    items.sort(key=lambda x: x.net_profit, reverse=True)

    return UnitEconomicsAllResponse(
        period_from=from_date,
        period_to=to_date,
        total_sales_count=grand_sales_count,
        total_quantity=grand_quantity,
        total_gross_revenue=grand_gross,
        total_net_revenue=grand_net,
        total_commission=grand_commission,
        total_logistics=grand_logistics,
        total_acquiring=grand_acquiring,
        total_storage=grand_storage,
        total_marketplace_costs=grand_costs,
        total_cogs=grand_cogs,
        total_tax=grand_tax,
        total_net_profit=grand_profit,
        total_advertising_cost=total_advertising_cost.quantize(Decimal("0.01")),
        drr_percent=(
            (total_advertising_cost / grand_net * Decimal("100")).quantize(Decimal("0.01"))
            if grand_net > 0
            else Decimal("0")
        ),
        total_net_profit_with_ads=(grand_profit - total_advertising_cost).quantize(Decimal("0.01")),
        products=items,
    )


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
    period_days = max(1, (to_date - from_date).days)

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
    contributions_per_sale = _prorated_contributions_per_sale(tax_settings, len(sales), period_days)
    results = [
        calculate_unit_economics(sale, product, tax_settings, contributions_per_sale)
        for sale in sales
    ]

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
            total_advertising_cost=Decimal("0"),
            drr_percent=Decimal("0"),
            total_net_profit_with_ads=Decimal("0"),
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
    period_days = max(1, (to_date - from_date).days)

    # 4. Группируем продажи по marketplace_id
    groups: dict[int, list[Sale]] = defaultdict(list)
    for sale in sales:
        groups[sale.marketplace_id].append(sale)

    # 5. Названия площадок — одним запросом
    marketplace_ids = list(groups.keys())
    mp_stmt = select(Marketplace).where(Marketplace.id.in_(marketplace_ids))
    marketplaces = (await session.execute(mp_stmt)).scalars().all()
    marketplace_map = {m.id: m for m in marketplaces}

    # 5.5. Реклама / ДРР
    adv = await _distribute_advertising_cost(session, current_user.id, from_date, to_date)
    adv_by_marketplace: dict[int, Decimal] = adv["by_marketplace"]
    total_advertising_cost = adv["total"]

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
        contributions_per_sale = _prorated_contributions_per_sale(
            tax_settings, len(marketplace_sales), period_days
        )
        results = [
            calculate_unit_economics(
                sale, products_map.get(sale.product_id or 0), tax_settings, contributions_per_sale
            )
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

        adv_cost = adv_by_marketplace.get(marketplace_id, Decimal("0")).quantize(Decimal("0.01"))
        drr_mp = (
            (adv_cost / revenue * Decimal("100")).quantize(Decimal("0.01"))
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
                advertising_cost=adv_cost,
                drr_percent=drr_mp,
                net_profit_with_ads=(net_profit - adv_cost).quantize(Decimal("0.01")),
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
        total_advertising_cost=total_advertising_cost.quantize(Decimal("0.01")),
        drr_percent=(
            (total_advertising_cost / grand_revenue * Decimal("100")).quantize(Decimal("0.01"))
            if grand_revenue > 0
            else Decimal("0")
        ),
        total_net_profit_with_ads=(grand_profit - total_advertising_cost).quantize(Decimal("0.01")),
        margin_percent=total_margin,
        by_marketplace=by_marketplace,
    )


@router.get("/abc", response_model=ABCAnalysisResponse)
async def abc_analysis(
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> ABCAnalysisResponse:
    """ABC-анализ ассортимента по вкладу в прибыль."""
    # 1. Все продажи за период
    sales_stmt = select(Sale).where(
        Sale.user_id == current_user.id,
        Sale.sold_at >= from_date,
        Sale.sold_at <= to_date,
        Sale.product_id.isnot(None),
    )
    sales = list((await session.execute(sales_stmt)).scalars().all())

    if not sales:
        return ABCAnalysisResponse(
            period_from=from_date,
            period_to=to_date,
            groups=[],
            products=[],
        )

    # 2. Товары — одним запросом
    product_ids = {sale.product_id for sale in sales if sale.product_id is not None}
    products_stmt = select(Product).where(Product.id.in_(product_ids))
    products = (await session.execute(products_stmt)).scalars().all()
    products_map = {p.id: p for p in products}

    # 3. Налоговые настройки
    tax_stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    tax_settings = (await session.execute(tax_stmt)).scalar_one_or_none()
    period_days = max(1, (to_date - from_date).days)

    # 4. Группируем по product_id
    product_stats: dict[int, dict[str, Decimal | int]] = defaultdict(
        lambda: {"revenue": Decimal("0"), "net_profit": Decimal("0"), "sales_count": 0}
    )

    for sale in sales:
        product = products_map.get(sale.product_id or 0)
        if product is None:
            continue
        contributions_per_sale = _prorated_contributions_per_sale(
            tax_settings, len(sales), period_days
        )
        r = calculate_unit_economics(sale, product, tax_settings, contributions_per_sale)
        pid = product.id
        product_stats[pid]["revenue"] += r.net_price * r.quantity
        product_stats[pid]["net_profit"] += r.net_profit
        product_stats[pid]["sales_count"] += 1

    # 5. Список товаров, отсортированный по прибыли (убывание)
    items: list[ABCProductItem] = []
    for pid, stats in product_stats.items():
        product = products_map[pid]
        items.append(
            ABCProductItem(
                product_id=pid,
                product_name=product.name,
                sku=product.sku,
                revenue=stats["revenue"],
                net_profit=stats["net_profit"],
                group="C",  # временно, назначим ниже
            )
        )
    items.sort(key=lambda x: x.net_profit, reverse=True)

    # 6. Считаем суммарную прибыль по положительным товарам
    total_positive_profit = sum(
        (item.net_profit for item in items if item.net_profit > 0), Decimal("0")
    )

    # 7. Разбиваем на группы
    if total_positive_profit > 0:
        cumulative_before = Decimal("0")
        threshold_a = total_positive_profit * Decimal("0.80")
        threshold_b = total_positive_profit * Decimal("0.95")

        for item in items:
            if item.net_profit <= 0:
                item.group = "C"
                continue

            # Группа определяется накопленной ДО добавления
            if cumulative_before < threshold_a:
                item.group = "A"
            elif cumulative_before < threshold_b:
                item.group = "B"
            else:
                item.group = "C"

            cumulative_before += item.net_profit
    else:
        # Все убыточные — все в C
        for item in items:
            item.group = "C"

    # 8. Статистика по группам
    total_revenue = sum((item.revenue for item in items), Decimal("0"))
    total_profit = sum((item.net_profit for item in items), Decimal("0"))

    groups: list[ABCGroupStats] = []
    for group_code in ("A", "B", "C"):
        group_items = [item for item in items if item.group == group_code]
        if not group_items:
            continue

        group_revenue = sum((item.revenue for item in group_items), Decimal("0"))
        group_profit = sum((item.net_profit for item in group_items), Decimal("0"))

        revenue_share = (
            (group_revenue / total_revenue * Decimal("100")).quantize(Decimal("0.01"))
            if total_revenue > 0
            else Decimal("0")
        )
        profit_share = (
            (group_profit / total_profit * Decimal("100")).quantize(Decimal("0.01"))
            if total_profit != 0
            else Decimal("0")
        )

        groups.append(
            ABCGroupStats(
                group=group_code,
                products_count=len(group_items),
                revenue=group_revenue,
                net_profit=group_profit,
                revenue_share_percent=revenue_share,
                profit_share_percent=profit_share,
            )
        )

    return ABCAnalysisResponse(
        period_from=from_date,
        period_to=to_date,
        groups=groups,
        products=items,
    )


@router.post("/calculator", response_model=CalculatorResponse)
async def calculator(
    payload: CalculatorRequest,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> CalculatorResponse:
    """Калькулятор юнит-экономики для нового товара (до закупки)."""
    # 1. Определяем налоговые параметры
    tax_system = payload.tax_system
    tax_rate = payload.tax_rate
    insurance_contributions = payload.insurance_contributions
    vat_enabled = payload.vat_enabled
    vat_rate = payload.vat_rate

    # Если tax_system не задан — берём из TaxSettings пользователя
    if tax_system is None:
        tax_stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
        settings = (await session.execute(tax_stmt)).scalar_one_or_none()
        if settings is not None:
            tax_system = settings.tax_system
            tax_rate = Decimal(settings.tax_rate)
            insurance_contributions = Decimal(settings.insurance_contributions)
            vat_enabled = settings.vat_enabled
            vat_rate = Decimal(settings.vat_rate)

    # 2. Считаем юнит-экономику
    economics = calculate_economics_from_params(
        target_price=payload.target_price,
        cost_price=payload.cost_price,
        quantity=payload.quantity,
        commission_percent=payload.commission_percent,
        logistics_cost=payload.logistics_cost,
        acquiring_percent=payload.acquiring_percent,
        storage_cost=payload.storage_cost,
        spp_percent=payload.spp_percent,
        tax_system=tax_system,
        tax_rate=tax_rate or Decimal("0"),
        insurance_contributions=insurance_contributions or Decimal("0"),
        vat_enabled=vat_enabled,
        vat_rate=vat_rate or Decimal("0"),
    )

    # 3. Warning + рекомендованная цена
    warning: str | None = None
    if economics.net_profit < Decimal("0"):
        # Считаем минимальную цену для маржи 10%
        effective_tax_rate = tax_rate or Decimal("0")
        recommended = calculate_recommended_price(
            cost_price=payload.cost_price,
            commission_percent=payload.commission_percent,
            acquiring_percent=payload.acquiring_percent,
            spp_percent=payload.spp_percent,
            logistics_cost=payload.logistics_cost,
            storage_cost=payload.storage_cost,
            target_margin_percent=Decimal("10"),
            tax_rate_percent=effective_tax_rate,
        )
        if recommended is not None:
            warning = (
                f"Текущая цена не покрывает затраты. "
                f"Рекомендуемая цена — не ниже {recommended} ₽ "
                f"(маржа 10%)"
            )
        else:
            warning = (
                "При таких параметрах прибыль недостижима — "
                "суммарные проценты комиссий превышают 100%"
            )

    return CalculatorResponse(
        gross_price=economics.gross_price,
        spp_amount=economics.spp_amount,
        net_price=economics.net_price,
        commission=economics.commission,
        logistics=economics.logistics,
        acquiring=economics.acquiring,
        storage=economics.storage,
        marketplace_costs_total=economics.marketplace_costs_total,
        payout=economics.payout,
        cogs=economics.cogs,
        gross_profit=economics.gross_profit,
        tax_amount=economics.tax_amount,
        net_profit=economics.net_profit,
        margin_percent=economics.margin_percent,
        roi_percent=economics.roi_percent,
        profit_per_unit=economics.profit_per_unit,
        warning=warning,
    )
