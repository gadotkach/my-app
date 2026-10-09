from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import (
    MarketplaceAccount,
    Product,
    Sale,
    TaxSettings,
    User,
    UserConsent,
)
from app.schemas import UserCreate, UserDeleteResponse, UserExportResponse, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> User:
    existing = await session.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )
    from app.security import hash_password

    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("", response_model=list[UserRead])
async def list_users(
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    result = await session.scalars(select(User).order_by(User.id))
    return list(result.all())


@router.get("/me", response_model=UserRead)
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# ============================================================
# ФЗ-152: Право на экспорт и удаление данных
# ============================================================


@router.get("/me/export", response_model=UserExportResponse)
async def export_me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserExportResponse:
    """Экспорт всех данных пользователя (152-ФЗ, право на доступ)."""
    # User
    user_data = {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "created_at": current_user.created_at.isoformat(),
        "subscription_status": current_user.subscription_status,
        "trial_started_at": current_user.trial_started_at.isoformat()
        if current_user.trial_started_at
        else None,
        "trial_ends_at": current_user.trial_ends_at.isoformat()
        if current_user.trial_ends_at
        else None,
        "subscription_ends_at": current_user.subscription_ends_at.isoformat()
        if current_user.subscription_ends_at
        else None,
        "last_activity_at": current_user.last_activity_at.isoformat()
        if current_user.last_activity_at
        else None,
    }

    # Products
    products_res = await session.scalars(select(Product).where(Product.user_id == current_user.id))
    products_data = [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "cost_price": str(p.cost_price) if p.cost_price else None,
            "created_at": p.created_at.isoformat(),
        }
        for p in products_res.all()
    ]

    # Sales
    sales_res = await session.scalars(select(Sale).where(Sale.user_id == current_user.id))
    sales_data = [
        {
            "id": s.id,
            "external_id": s.external_id,
            "quantity": s.quantity,
            "price": str(s.price),
            "sold_at": s.sold_at.isoformat(),
        }
        for s in sales_res.all()
    ]

    # Integrations
    integ_res = await session.scalars(
        select(MarketplaceAccount).where(MarketplaceAccount.user_id == current_user.id)
    )
    integrations_data = [
        {
            "id": i.id,
            "marketplace_id": i.marketplace_id,
            "client_id": i.client_id,
            "created_at": i.created_at.isoformat(),
            "last_sync_at": i.last_sync_at.isoformat() if i.last_sync_at else None,
        }
        for i in integ_res.all()
    ]

    # Tax settings
    tax = await session.scalar(select(TaxSettings).where(TaxSettings.user_id == current_user.id))
    tax_data = None
    if tax is not None:
        tax_data = {
            "id": tax.id,
            "tax_system": tax.tax_system,
            "tax_rate": str(tax.tax_rate),
            "insurance_contributions": str(tax.insurance_contributions)
            if tax.insurance_contributions
            else None,
            "vat_enabled": tax.vat_enabled,
            "vat_rate": str(tax.vat_rate) if tax.vat_rate else None,
        }

    # Consents
    consents_res = await session.scalars(
        select(UserConsent).where(UserConsent.user_id == current_user.id)
    )
    consents_data = [
        {
            "consent_type": c.consent_type,
            "granted_at": c.granted_at.isoformat(),
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            "ip_address": c.ip_address,
        }
        for c in consents_res.all()
    ]

    return UserExportResponse(
        user=user_data,
        products=products_data,
        sales=sales_data,
        integrations=integrations_data,
        tax_settings=tax_data,
        consents=consents_data,
        exported_at=datetime.now(UTC),
    )


@router.delete("/me", response_model=UserDeleteResponse)
async def delete_me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserDeleteResponse:
    """Soft delete аккаунта (152-ФЗ, право на удаление).

    Аккаунт помечается deleted_at. Через 30 дней — hard delete (cron).
    До этого момента — восстановление возможно через поддержку.
    """
    if current_user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account already scheduled for deletion",
        )

    now = datetime.now(UTC)
    deletion_scheduled = now + timedelta(days=30)

    # Анонимизация email (чтобы освободить для повторной регистрации)
    anonymized_email = f"deleted_{uuid4().hex}@deleted.local"
    current_user.email = anonymized_email
    current_user.deleted_at = now

    await session.commit()
    await session.refresh(current_user)

    return UserDeleteResponse(
        deleted=True,
        deletion_scheduled_at=deletion_scheduled,
        detail=(
            "Аккаунт помечен на удаление. Через 30 дней данные будут "
            "удалены безвозвратно. Для восстановления обратитесь в поддержку."
        ),
    )
