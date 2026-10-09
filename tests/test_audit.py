"""Тесты AuditLog (ФЗ-152): логирование доступа к ПДн."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


async def test_login_creates_audit_log(client: AsyncClient, engine):
    """POST /auth/login пишет запись в audit_logs."""
    # Register
    await client.post(
        "/auth/register",
        json={
            "email": "audit-1@example.com",
            "name": "Audit",
            "password": "secret123",
        },
    )

    # Login
    response = await client.post(
        "/auth/login",
        json={"email": "audit-1@example.com", "password": "secret123"},
    )
    assert response.status_code == 200

    # Проверим audit_logs
    from app.models import AuditLog

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        logs = (await s.scalars(select(AuditLog).where(AuditLog.action == "login"))).all()
        assert len(logs) >= 1
        log = logs[-1]
        assert log.action == "login"
        assert log.resource == "/auth/login"
        assert log.user_id is not None
        assert log.metadata_json is not None
        assert log.metadata_json["method"] == "POST"
        assert log.metadata_json["status"] == 200


async def test_register_creates_audit_log(client: AsyncClient, engine):
    """POST /auth/register пишет запись в audit_logs."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "audit-2@example.com",
            "name": "Audit",
            "password": "secret123",
        },
    )
    assert response.status_code == 201

    from app.models import AuditLog

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        logs = (await s.scalars(select(AuditLog).where(AuditLog.action == "register"))).all()
        assert len(logs) >= 1
        assert logs[-1].resource == "/auth/register"


async def test_export_creates_audit_log(client: AsyncClient, engine):
    """GET /users/me/export пишет audit_log."""
    await client.post(
        "/auth/register",
        json={
            "email": "audit-3@example.com",
            "name": "Audit",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "audit-3@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/users/me/export", headers=headers)
    assert response.status_code == 200

    from app.models import AuditLog

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        logs = (await s.scalars(select(AuditLog).where(AuditLog.action == "export"))).all()
        assert len(logs) >= 1
        assert logs[-1].resource == "/users/me/export"


async def test_consent_creates_audit_log(client: AsyncClient, engine):
    """POST /auth/consent/accept пишет audit_log."""
    await client.post(
        "/auth/register",
        json={
            "email": "audit-4@example.com",
            "name": "Audit",
            "password": "secret123",
        },
    )
    login = await client.post(
        "/auth/login",
        json={"email": "audit-4@example.com", "password": "secret123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/auth/consent/accept",
        json={"consent_type": "marketing"},
        headers=headers,
    )
    assert response.status_code == 200

    from app.models import AuditLog

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        logs = (await s.scalars(select(AuditLog).where(AuditLog.action == "consent"))).all()
        assert len(logs) >= 1


async def test_health_not_logged(client: AsyncClient, engine):
    """GET /health НЕ пишет audit_log."""
    await client.get("/health")

    from app.models import AuditLog

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        logs = (await s.scalars(select(AuditLog).where(AuditLog.resource == "/health"))).all()
        assert len(logs) == 0
