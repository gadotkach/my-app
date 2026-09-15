"""Сервис расчёта юнит-экономики селлера."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models import Product, Sale, TaxSettings

# --- Константы ---
ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass
class UnitEconomics:
    """Результат расчёта юнит-экономики по одной продаже."""

    # Входные данные
    gross_price: Decimal          # цена, установленная селлером
    quantity: int                 # количество единиц

    # СПП
    spp_amount: Decimal           # сумма скидки постоянного покупателя
    net_price: Decimal            # цена после СПП (то, что реально платит покупатель)

    # Расходы площадки
    commission: Decimal
    logistics: Decimal
    return_logistics: Decimal
    acquiring: Decimal
    storage: Decimal
    marketplace_costs_total: Decimal  # сумма всех расходов площадки

    # Payout и себестоимость
    payout: Decimal               # выплата от площадки
    cogs: Decimal                 # себестоимость (cost of goods sold)
    gross_profit: Decimal         # валовая прибыль (payout − cogs)

    # Налоги и итог
    tax_amount: Decimal
    net_profit: Decimal           # чистая прибыль

    # Метрики
    margin_percent: Decimal       # маржа в % от net_price
    roi_percent: Decimal          # ROI в % от cogs
    profit_per_unit: Decimal      # прибыль с одной единицы


def _round(value: Decimal) -> Decimal:
    """Округлить до копеек (2 знака после запятой)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_tax(
    *,
    tax_system: str,
    tax_rate: Decimal,
    revenue: Decimal,
    expenses: Decimal,
    insurance_contributions: Decimal,
    vat_enabled: bool = False,
    vat_rate: Decimal = ZERO,
) -> Decimal:
    """
    Рассчитать налог в зависимости от системы налогообложения.

    Args:
        tax_system: 'NPD' | 'USN_INCOME' | 'USN_INCOME_EXPENSE' | 'PSN'
        tax_rate: ставка в процентах (4, 6, 15)
        revenue: выручка (net_price × quantity)
        expenses: расходы площадки + себестоимость (для УСН Д−Р)
        insurance_contributions: фиксированные страховые взносы ИП
        vat_enabled: включён ли НДС
        vat_rate: ставка НДС в процентах

    Returns:
        Decimal: сумма налога
    """
    tax = ZERO

    if tax_system == "NPD":
        # НПД: 4% с физлиц, 6% с юрлиц. Расходы не учитываются.
        tax = revenue * tax_rate / HUNDRED

    elif tax_system == "USN_INCOME":
        # УСН «Доходы»: налог с выручки, уменьшается на страховые взносы.
        tax = revenue * tax_rate / HUNDRED
        tax = max(ZERO, tax - insurance_contributions)

    elif tax_system == "USN_INCOME_EXPENSE":
        # УСН «Доходы − расходы»: налог с прибыли.
        base = revenue - expenses
        if base > ZERO:
            tax = base * tax_rate / HUNDRED

    elif tax_system == "PSN":
        # Патент: фиксированная сумма, в этом расчёте не учитывается.
        tax = ZERO

    # НДС добавляется сверху, если включён
    if vat_enabled:
        tax += revenue * vat_rate / HUNDRED

    return _round(tax)


def calculate_unit_economics(
    sale: Sale,
    product: Product | None,
    tax_settings: TaxSettings | None,
) -> UnitEconomics:
    """
    Рассчитать юнит-экономику одной продажи.

    Args:
        sale: запись о продаже
        product: товар (для себестоимости). Может быть None, если товар удалён.
        tax_settings: настройки налогообложения пользователя. Может быть None.

    Returns:
        UnitEconomics: полный расчёт
    """
    quantity = Decimal(sale.quantity or 1)
    gross_price = Decimal(sale.price or ZERO)

    # --- СПП ---
    spp_amount = Decimal(sale.spp_amount or ZERO)
    net_price = gross_price - spp_amount

    # --- Расходы площадки ---
    commission = Decimal(sale.commission or ZERO)
    logistics = Decimal(sale.logistics_cost or ZERO)
    return_logistics = Decimal(sale.return_logistics_cost or ZERO)
    acquiring = Decimal(sale.acquiring_fee or ZERO)
    storage = Decimal(sale.storage_cost or ZERO)

    marketplace_costs_total = (
        commission + logistics + return_logistics + acquiring + storage
    )

    # --- Payout (что перечислила площадка) ---
    payout = net_price - marketplace_costs_total

    # --- Себестоимость ---
    cogs_per_unit = Decimal(product.cost_price or ZERO) if product else ZERO
    cogs = cogs_per_unit * quantity

    # --- Валовая прибыль ---
    gross_profit = payout - cogs

    # --- Налоги ---
    revenue = net_price * quantity
    expenses = marketplace_costs_total + cogs

    if tax_settings:
        tax_amount = calculate_tax(
            tax_system=tax_settings.tax_system,
            tax_rate=Decimal(tax_settings.tax_rate),
            revenue=revenue,
            expenses=expenses,
            insurance_contributions=Decimal(tax_settings.insurance_contributions),
            vat_enabled=tax_settings.vat_enabled,
            vat_rate=Decimal(tax_settings.vat_rate),
        )
    else:
        tax_amount = ZERO

    # --- Чистая прибыль ---
    net_profit = gross_profit - tax_amount

    # --- Метрики ---
    margin_percent = (
        _round(net_profit / revenue * HUNDRED) if revenue > ZERO else ZERO
    )
    roi_percent = (
        _round(net_profit / cogs * HUNDRED) if cogs > ZERO else ZERO
    )
    profit_per_unit = _round(net_profit / quantity) if quantity > ZERO else ZERO

    return UnitEconomics(
        gross_price=_round(gross_price),
        quantity=int(quantity),
        spp_amount=_round(spp_amount),
        net_price=_round(net_price),
        commission=_round(commission),
        logistics=_round(logistics),
        return_logistics=_round(return_logistics),
        acquiring=_round(acquiring),
        storage=_round(storage),
        marketplace_costs_total=_round(marketplace_costs_total),
        payout=_round(payout),
        cogs=_round(cogs),
        gross_profit=_round(gross_profit),
        tax_amount=_round(tax_amount),
        net_profit=_round(net_profit),
        margin_percent=margin_percent,
        roi_percent=roi_percent,
        profit_per_unit=profit_per_unit,
    )