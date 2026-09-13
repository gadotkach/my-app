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


class ProductRead(BaseModel):
    id: int
    sku: str
    name: str
    description: str | None
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
