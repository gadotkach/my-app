from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app import models  # noqa: F401
from app.config import settings
from app.database import Base
from app.deps import get_session
from app.main import app as fastapi_app
from app.models import DeliveryService, Marketplace, Product, Sale, User


@pytest_asyncio.fixture(scope="session")
async def engine():
    # Для SQLite in-memory нужен StaticPool — одно соединение на всех
    # Для Postgres — NullPool (каждое соединение своё, свой loop)
    pool_class = StaticPool if "sqlite" in settings.test_database_url.lower() else NullPool
    engine = create_async_engine(
        settings.test_database_url,
        echo=False,
        poolclass=pool_class,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine) -> AsyncGenerator[AsyncClient, None]:
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def clean_db(engine):
    """Clean business data between tests, keep reference data intact."""
    from app.models import (
        ApiRequestLog,
        Marketplace,
        MarketplaceAccount,
        OzonAdsAccount,
        RefreshToken,
        TaxSettings,
        TelegramSubscription,
        TrialIdentity,
        UserConsent,
    )

    async with engine.begin() as conn:
        # Удаляем бизнес-данные, но НЕ справочники (marketplaces, delivery_services)
        await conn.execute(delete(TaxSettings))
        await conn.execute(delete(Sale))
        await conn.execute(delete(Product))
        await conn.execute(delete(RefreshToken))
        await conn.execute(delete(MarketplaceAccount))
        await conn.execute(delete(TelegramSubscription))
        await conn.execute(delete(OzonAdsAccount))  # ← ДО User (FK)
        await conn.execute(delete(ApiRequestLog))  # ← ДО User (FK)
        await conn.execute(delete(UserConsent))  # ← ДО User (FK)
        await conn.execute(delete(TrialIdentity))
        await conn.execute(delete(User))
        # Пересоздаём справочники (могут быть удалены предыдущим тестом)
        await conn.execute(delete(Marketplace))
        await conn.execute(delete(DeliveryService))
    yield


@pytest_asyncio.fixture(autouse=True)
async def seed_reference_data(engine, clean_db):
    """Seed marketplaces and delivery services before each test."""
    from app.models import DeliveryService

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        marketplaces = [
            Marketplace(code="ozon", name="Ozon"),
            Marketplace(code="wildberries", name="Wildberries"),
            Marketplace(code="yandex_market", name="Яндекс.Маркет"),
            Marketplace(code="aliexpress", name="AliExpress"),
            Marketplace(code="avito", name="Авито"),
        ]
        delivery_services = [
            DeliveryService(code="cdek", name="СДЭК"),
            DeliveryService(code="boxberry", name="Boxberry"),
            DeliveryService(code="russian_post", name="Почта России"),
            DeliveryService(code="dhl", name="DHL"),
        ]
        session.add_all(marketplaces)
        session.add_all(delivery_services)
        await session.commit()
    yield


@pytest_asyncio.fixture(autouse=True, scope="session")
async def _test_cookie_settings():
    """Force test-friendly cookie settings regardless of .env.

    VPS-окружение содержит COOKIE_SECURE=true и COOKIE_DOMAIN=.agregators.su.
    В тестах это ломает работу cookies (HTTP + домен test).
    Принудительно ставим безопасные значения на время тестов.
    """
    settings.cookie_secure = False
    settings.cookie_domain = None
    yield


# ============================================================
# Фикстуры аутентификации
# ============================================================


@pytest_asyncio.fixture
async def auth_headers(client) -> dict[str, str]:
    """Зарегистрировать юзера и вернуть Authorization-заголовок."""
    email = "testuser@example.com"
    password = "secret123"

    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Test User"},
    )
    assert resp.status_code in (200, 201), f"Register failed: {resp.text}"

    # /auth/register возвращает UserRead, не Token → логинимся отдельно
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_user_headers(client) -> dict[str, str]:
    """Второй юзер для тестов изоляции."""
    email = "second@example.com"
    password = "secret123"

    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Second User"},
    )
    assert resp.status_code in (200, 201), f"Register failed: {resp.text}"

    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
