"""Тесты расчёта юнит-экономики."""

from decimal import Decimal

from app.services.unit_economics import calculate_tax, calculate_unit_economics


# --- Заглушки: простые объекты вместо SQLAlchemy-моделей ---
class FakeSale:
    def __init__(self, **kwargs):
        defaults = {
            "quantity": 1,
            "price": Decimal("1000"),
            "spp_amount": Decimal("0"),
            "commission": Decimal("0"),
            "logistics_cost": Decimal("0"),
            "return_logistics_cost": Decimal("0"),
            "acquiring_fee": Decimal("0"),
            "storage_cost": Decimal("0"),
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


class FakeProduct:
    def __init__(self, cost_price=None):
        self.cost_price = cost_price


class FakeTaxSettings:
    def __init__(self, **kwargs):
        defaults = {
            "tax_system": "USN_INCOME",
            "tax_rate": Decimal("6"),
            "insurance_contributions": Decimal("0"),
            "vat_enabled": False,
            "vat_rate": Decimal("0"),
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


# ============================================================
# 1. Базовые расчёты
# ============================================================


def test_profitable_sale_without_tax():
    """Продажа с прибылью, налоги не заданы."""
    sale = FakeSale(
        price=Decimal("1000"),
        commission=Decimal("150"),
        logistics_cost=Decimal("100"),
        acquiring_fee=Decimal("10"),
    )
    product = FakeProduct(cost_price=Decimal("500"))

    result = calculate_unit_economics(sale, product, tax_settings=None)

    assert result.net_price == Decimal("1000")
    assert result.marketplace_costs_total == Decimal("260")  # 150 + 100 + 10
    assert result.payout == Decimal("740")
    assert result.cogs == Decimal("500")
    assert result.gross_profit == Decimal("240")
    assert result.tax_amount == Decimal("0")
    assert result.net_profit == Decimal("240")
    assert result.margin_percent == Decimal("24.00")


def test_loss_making_sale():
    """Продажа с убытком."""
    sale = FakeSale(
        price=Decimal("1000"),
        commission=Decimal("300"),
        logistics_cost=Decimal("150"),
        acquiring_fee=Decimal("20"),
    )
    product = FakeProduct(cost_price=Decimal("700"))

    result = calculate_unit_economics(sale, product, tax_settings=None)

    # 1000 - 470 = 530 payout
    # 530 - 700 = -170 убыток
    assert result.payout == Decimal("530")
    assert result.gross_profit == Decimal("-170")
    assert result.net_profit == Decimal("-170")
    assert result.margin_percent == Decimal("-17.00")


def test_spp_reduces_revenue():
    """СПП уменьшает выручку."""
    sale = FakeSale(
        price=Decimal("1000"),
        spp_amount=Decimal("200"),  # СПП 200 руб
        commission=Decimal("150"),
    )
    product = FakeProduct(cost_price=Decimal("500"))

    result = calculate_unit_economics(sale, product, tax_settings=None)

    assert result.spp_amount == Decimal("200")
    assert result.net_price == Decimal("800")  # 1000 − 200
    # payout = 800 − 150 = 650
    # gross_profit = 650 − 500 = 150
    assert result.payout == Decimal("650")
    assert result.gross_profit == Decimal("150")


def test_zero_cost_price():
    """Себестоимость не задана — не должно быть деления на ноль."""
    sale = FakeSale(price=Decimal("500"), commission=Decimal("100"))
    product = FakeProduct(cost_price=None)

    result = calculate_unit_economics(sale, product, tax_settings=None)

    assert result.cogs == Decimal("0")
    assert result.roi_percent == Decimal("0")  # защита от деления на ноль
    assert result.gross_profit == Decimal("400")


def test_product_is_none():
    """Товар удалён — расчёт без себестоимости."""
    sale = FakeSale(price=Decimal("1000"), commission=Decimal("150"))
    result = calculate_unit_economics(sale, product=None, tax_settings=None)

    assert result.cogs == Decimal("0")
    assert result.gross_profit == Decimal("850")


def test_quantity_multiplies_revenue_and_cogs():
    """Количество умножает выручку и себестоимость."""
    sale = FakeSale(
        quantity=3,
        price=Decimal("1000"),
        commission=Decimal("150"),
        logistics_cost=Decimal("50"),
    )
    product = FakeProduct(cost_price=Decimal("400"))

    result = calculate_unit_economics(sale, product, tax_settings=None)

    # payout с одной единицы: 1000 − 200 = 800
    # но payout в UnitEconomics — за всю продажу (без × quantity)
    # cogs = 400 × 3 = 1200
    assert result.cogs == Decimal("1200")
    # profit_per_unit = net_profit / quantity
    # net_profit = 800 − 1200 = −400
    assert result.net_profit == Decimal("-400")
    # −400 / 3 = −133.33
    assert result.profit_per_unit == Decimal("-133.33")


# ============================================================
# 2. Налоговые системы
# ============================================================


def test_tax_npd():
    """НПД: 4% с дохода, расходы не учитываются."""
    tax = calculate_tax(
        tax_system="NPD",
        tax_rate=Decimal("4"),
        revenue=Decimal("10000"),
        expenses=Decimal("8000"),
        insurance_contributions=Decimal("0"),
    )
    assert tax == Decimal("400.00")


def test_tax_usn_income():
    """УСН Доходы: 6% с выручки минус взносы."""
    tax = calculate_tax(
        tax_system="USN_INCOME",
        tax_rate=Decimal("6"),
        revenue=Decimal("10000"),
        expenses=Decimal("8000"),
        insurance_contributions=Decimal("200"),
    )
    # 10000 × 6% = 600; 600 − 200 = 400
    assert tax == Decimal("400.00")


def test_tax_usn_income_insurance_exceeds():
    """УСН Доходы: взносы больше налога — налог = 0."""
    tax = calculate_tax(
        tax_system="USN_INCOME",
        tax_rate=Decimal("6"),
        revenue=Decimal("10000"),
        expenses=Decimal("0"),
        insurance_contributions=Decimal("1000"),  # больше, чем 600
    )
    assert tax == Decimal("0")


def test_tax_usn_income_expense():
    """УСН Д−Р: 15% с прибыли."""
    tax = calculate_tax(
        tax_system="USN_INCOME_EXPENSE",
        tax_rate=Decimal("15"),
        revenue=Decimal("10000"),
        expenses=Decimal("8000"),
        insurance_contributions=Decimal("0"),
    )
    # (10000 − 8000) × 15% = 300
    assert tax == Decimal("300.00")


def test_tax_usn_income_expense_loss():
    """УСН Д−Р: убыток — налог = 0."""
    tax = calculate_tax(
        tax_system="USN_INCOME_EXPENSE",
        tax_rate=Decimal("15"),
        revenue=Decimal("10000"),
        expenses=Decimal("12000"),  # больше выручки
        insurance_contributions=Decimal("0"),
    )
    assert tax == Decimal("0")


def test_tax_with_vat():
    """НДС добавляется сверху."""
    tax = calculate_tax(
        tax_system="USN_INCOME",
        tax_rate=Decimal("6"),
        revenue=Decimal("10000"),
        expenses=Decimal("0"),
        insurance_contributions=Decimal("0"),
        vat_enabled=True,
        vat_rate=Decimal("20"),
    )
    # 600 (УСН) + 2000 (НДС) = 2600
    assert tax == Decimal("2600.00")


# ============================================================
# 3. Интеграция: sale + tax_settings
# ============================================================


def test_full_calculation_with_usn_income():
    """Полный расчёт: продажа + УСН Доходы 6% + взносы."""
    sale = FakeSale(
        price=Decimal("1000"),
        commission=Decimal("150"),
        logistics_cost=Decimal("100"),
    )
    product = FakeProduct(cost_price=Decimal("500"))
    tax = FakeTaxSettings(
        tax_system="USN_INCOME",
        tax_rate=Decimal("6"),
        insurance_contributions=Decimal("0"),
    )

    result = calculate_unit_economics(sale, product, tax)

    # payout = 1000 − 250 = 750; gross_profit = 750 − 500 = 250
    # tax = 1000 × 6% = 60
    # net_profit = 250 − 60 = 190
    assert result.gross_profit == Decimal("250")
    assert result.tax_amount == Decimal("60.00")
    assert result.net_profit == Decimal("190")
    assert result.margin_percent == Decimal("19.00")
