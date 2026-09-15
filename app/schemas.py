from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str


class UserRead(BaseModel):
    id: int
    email: EmailStr
    name: str
    created_at: datetime
    subscription_status: str
    trial_ends_at: datetime | None
    subscription_ends_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MarketplaceRead(BaseModel):
    id: int
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str | None = None
    cost_price: Decimal | None = None
    volume_liters: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None


class ProductRead(BaseModel):
    id: int
    sku: str
    name: str
    description: str | None
    cost_price: Decimal | None
    volume_liters: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SaleCreate(BaseModel):
    marketplace_code: str
    product_id: int | None = None
    delivery_service_code: str | None = None
    external_id: str
    quantity: int = 1
    price: Decimal
    commission: Decimal = Decimal("0")
    logistics_cost: Decimal = Decimal("0")
    sold_at: datetime


class SaleRead(BaseModel):
    id: int
    marketplace_id: int
    product_id: int | None
    delivery_service_id: int | None
    external_id: str
    quantity: int
    price: Decimal
    commission: Decimal
    logistics_cost: Decimal
    sold_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketplaceCreate(BaseModel):
    code: str
    name: str


class DeliveryServiceCreate(BaseModel):
    code: str
    name: str


class DeliveryServiceRead(BaseModel):
    id: int
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class AnalyticsSummary(BaseModel):
    period_from: datetime
    period_to: datetime
    sales_count: int
    total_revenue: Decimal
    total_commission: Decimal
    total_logistics: Decimal
    net_profit: Decimal


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MarketplaceStats(BaseModel):
    marketplace_code: str
    marketplace_name: str
    sales_count: int
    total_revenue: Decimal
    total_commission: Decimal
    total_logistics: Decimal
    net_profit: Decimal


class ProductStats(BaseModel):
    product_id: int | None
    product_name: str | None
    sales_count: int
    total_revenue: Decimal


class MarketplaceAccountConnect(BaseModel):
    marketplace_code: str  # например, "ozon"
    client_id: str
    api_key: str


class MarketplaceAccountRead(BaseModel):
    id: int
    marketplace_code: str
    client_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OzonSyncResult(BaseModel):
    synced: int
    created: int
    updated: int


class OzonSyncSalesResult(BaseModel):
    synced: int
    created: int
    updated: int
    period_from: datetime
    period_to: datetime


# ============================================================
# Юнит-экономика
# ============================================================


class TaxSettingsUpsert(BaseModel):
    """Тело запроса для создания/обновления налоговых настроек."""

    tax_system: str  # 'NPD' | 'USN_INCOME' | 'USN_INCOME_EXPENSE' | 'PSN'
    tax_rate: Decimal
    insurance_contributions: Decimal = Decimal("57390")
    vat_enabled: bool = False
    vat_rate: Decimal = Decimal("0")


class TaxSettingsRead(BaseModel):
    id: int
    tax_system: str
    tax_rate: Decimal
    insurance_contributions: Decimal
    vat_enabled: bool
    vat_rate: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UnitEconomicsResponse(BaseModel):
    """Полный расчёт юнит-экономики по одному товару за период."""

    product_id: int
    product_name: str
    sku: str
    period_from: datetime
    period_to: datetime
    sales_count: int
    quantity: int

    # Выручка
    gross_revenue: Decimal
    spp_amount: Decimal
    net_revenue: Decimal

    # Расходы площадки
    commission: Decimal
    logistics: Decimal
    return_logistics: Decimal
    acquiring: Decimal
    storage: Decimal
    marketplace_costs_total: Decimal

    # Payout, себестоимость, налог
    payout: Decimal
    cogs: Decimal
    gross_profit: Decimal
    tax_amount: Decimal
    net_profit: Decimal

    # Метрики
    margin_percent: Decimal
    roi_percent: Decimal
    profit_per_unit: Decimal

    warning: str | None = None


class ProfitByMarketplace(BaseModel):
    marketplace_code: str
    marketplace_name: str
    sales_count: int
    revenue: Decimal
    marketplace_costs: Decimal
    cogs: Decimal
    tax_amount: Decimal
    net_profit: Decimal
    margin_percent: Decimal


class ProfitSummaryResponse(BaseModel):
    period_from: datetime
    period_to: datetime
    total_revenue: Decimal
    total_marketplace_costs: Decimal
    total_cogs: Decimal
    total_tax: Decimal
    total_net_profit: Decimal
    margin_percent: Decimal
    by_marketplace: list[ProfitByMarketplace]


class ABCGroupStats(BaseModel):
    group: str  # 'A' | 'B' | 'C'
    products_count: int
    revenue: Decimal
    net_profit: Decimal
    revenue_share_percent: Decimal
    profit_share_percent: Decimal


class ABCProductItem(BaseModel):
    product_id: int
    product_name: str
    sku: str
    revenue: Decimal
    net_profit: Decimal
    group: str


class ABCAnalysisResponse(BaseModel):
    period_from: datetime
    period_to: datetime
    groups: list[ABCGroupStats]
    products: list[ABCProductItem]


class CalculatorRequest(BaseModel):
    """Вход для калькулятора юнит-экономики (до закупки)."""

    cost_price: Decimal
    target_price: Decimal
    quantity: int = 1

    # Расходы площадки (в % от net_price или в рублях)
    commission_percent: Decimal = Decimal("0")
    logistics_cost: Decimal = Decimal("0")
    acquiring_percent: Decimal = Decimal("0")
    storage_cost: Decimal = Decimal("0")

    # СПП
    spp_percent: Decimal = Decimal("0")

    # Налоги (можно не указывать — берётся из TaxSettings)
    tax_system: str | None = None
    tax_rate: Decimal | None = None
    insurance_contributions: Decimal | None = None
    vat_enabled: bool = False
    vat_rate: Decimal = Decimal("0")


class CalculatorResponse(BaseModel):
    """Результат расчёта в калькуляторе."""

    gross_price: Decimal
    spp_amount: Decimal
    net_price: Decimal
    commission: Decimal
    logistics: Decimal
    acquiring: Decimal
    storage: Decimal
    marketplace_costs_total: Decimal
    payout: Decimal
    cogs: Decimal
    gross_profit: Decimal
    tax_amount: Decimal
    net_profit: Decimal
    margin_percent: Decimal
    roi_percent: Decimal
    profit_per_unit: Decimal
    warning: str | None = None
