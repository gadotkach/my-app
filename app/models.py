from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    hashed_password: Mapped[str] = mapped_column(String(255))
    yandex_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Подписка / пробный период
    subscription_status: Mapped[str] = mapped_column(String(20), default="none", index=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Email Verification (double opt-in)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    # Защита от вечного trial: причина отмены (например, "marketplace_already_used")
    trial_revoked_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # ФЗ-152: soft delete (30 дней до hard delete)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    tax_settings: Mapped["TaxSettings | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Marketplace(Base):
    __tablename__ = "marketplaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    # known values: ozon, wildberries, yandex_market, aliexpress, avito
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sales: Mapped[list["Sale"]] = relationship(back_populates="marketplace")


class DeliveryService(Base):
    __tablename__ = "delivery_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    # known values: cdek, boxberry, russian_post, dhl
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sales: Mapped[list["Sale"]] = relationship(back_populates="delivery_service")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("user_id", "sku", name="uq_products_user_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Юнит-экономика ---
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume_liters: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    sales: Mapped[list["Sale"]] = relationship(back_populates="product")


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplaces.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delivery_service_id: Mapped[int | None] = mapped_column(
        ForeignKey("delivery_services.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    quantity: Mapped[int] = mapped_column(default=1)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Юнит-экономика: расходы площадки ---
    commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    commission_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    logistics_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    return_logistics_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    acquiring_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    acquiring_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    storage_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    # --- СПП ---
    spp_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    spp_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    retail_price_with_spp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # --- Итоговая выплата от площадки ---
    payout_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    marketplace: Mapped[Marketplace] = relationship(back_populates="sales")
    product: Mapped[Product | None] = relationship(back_populates="sales")
    delivery_service: Mapped[DeliveryService | None] = relationship(back_populates="sales")


class MarketplaceAccount(Base):
    __tablename__ = "marketplace_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_id: Mapped[int] = mapped_column(ForeignKey("marketplaces.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
    marketplace: Mapped["Marketplace"] = relationship()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()


class EmailVerificationToken(Base):
    """Токен подтверждения email (152-ФЗ + double opt-in).

    Хранит sha256-хеш токена (не открытый текст).
    Токен живёт 24 часа (больше, чем у password reset — email может быть забыт).
    used_at — после успешного подтверждения.
    """

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()


class PasswordResetToken(Base):
    """Токен восстановления пароля (152-ФЗ).

    Хранит sha256-хеш токена (не открытый текст).
    Токен живёт 1 час. used_at — после успешной смены пароля.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()


class UsedMarketplaceIdentity(Base):
    """Хранит все когда-либо подключённые маркетплейс-идентификаторы.

    Цель: не давать вечный trial при смене email + IP.
    Ключ: identity_hash = sha256(client_id или api_key).
    """

    __tablename__ = "used_marketplace_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace_code: Mapped[str] = mapped_column(String(50), index=True)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    first_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TrialIdentity(Base):
    """Защита от повторного получения trial. Одна запись = один trial."""

    __tablename__ = "trial_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    """История платежей. Заполняется из webhook провайдера (ЮKassa и т.п.)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(50))  # yookassa, cloudpayments, ...
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, succeeded, canceled
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaxSettings(Base):
    __tablename__ = "tax_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Система налогообложения: 'NPD', 'USN_INCOME', 'USN_INCOME_EXPENSE', 'PSN'
    tax_system: Mapped[str] = mapped_column(String(30))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    # Фиксированные страховые взносы ИП (в 2026 = 57 390 ₽)
    insurance_contributions: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("57390")
    )

    # НДС
    vat_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="tax_settings")


class AdvertisingExpense(Base):
    """
    Расходы на рекламу. Может быть привязан к площадке и/или товару.
    Используется для расчёта ДРР (доля рекламных расходов).

    Источники (source):
    - 'ozon_ads'       — внутренняя реклама Ozon (Продвижение, Трафареты)
    - 'wb_adv'         — внутренняя реклама WB (Поиск, Автореклама, Аукцион)
    - 'yandex_direct'  — Яндекс.Директ
    - 'vk_ads'         — VK Реклама
    - 'telegram_ads'   — Telegram Ads
    - 'manual'         — ручной ввод (неклассифицированные)
    """

    __tablename__ = "advertising_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    marketplace_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketplaces.id"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(50), index=True)
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    marketplace: Mapped["Marketplace | None"] = relationship()
    product: Mapped["Product | None"] = relationship()


class OzonAdsAccount(Base):
    """
    Credentials для Ozon Performance API (Ozon Ads).

    Хранит Client ID (не секрет) и Client Secret (зашифрован Fernet).
    Используется для автоматического сбора рекламных расходов Ozon.

    Client ID выглядит так:
    '106448101-1791440182845@advertising.performance.ozon.ru'
    Получить: seller.ozon.ru → Настройки → API-ключи → Performance.
    """

    __tablename__ = "ozon_ads_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, unique=True
    )
    client_id: Mapped[str] = mapped_column(String(255))
    client_secret_encrypted: Mapped[str] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship()


class TelegramSubscription(Base):
    """
    Подписка пользователя на Telegram-уведомления.

    Хранит chat_id пользователя в Telegram и настройки уведомлений.
    Один User — одна подписка (one-to-one).
    """

    __tablename__ = "telegram_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )
    chat_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Что уведомлять
    notify_new_sales: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_loss_making: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_daily_report: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_drr_high: Mapped[bool] = mapped_column(Boolean, default=True)

    # Порог ДРР в %
    drr_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("50.0"))

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_notification_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship()


class ApiRequestLog(Base):
    """Лог API-запросов к маркетплейсам (для аудита и оптимизации).

    Записывается через httpx event hooks (асинхронно, без блокировки).
    """

    __tablename__ = "api_request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    marketplace: Mapped[str] = mapped_column(String(50), index=True)
    method: Mapped[str] = mapped_column(String(10))
    endpoint: Mapped[str] = mapped_column(String(255), index=True)
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class UserConsent(Base):
    """Согласие субъекта ПДн на обработку (152-ФЗ).

    Хранит факт согласия: тип, время, IP, user-agent.
    При отзыве — revoked_at заполняется, запись сохраняется (для аудита).
    """

    __tablename__ = "user_consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    consent_type: Mapped[str] = mapped_column(String(50), index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "consent_type", name="uq_user_consent_type"),)

    user: Mapped["User"] = relationship()


class AuditLog(Base):
    """Лог доступа к ПДн (152-ФЗ, требование РКН — хранение 1 год).

    Логируются только чувствительные эндпоинты:
    login, register, logout, consent/*, users/me/*, integrations/*.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), index=True)
    resource: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
