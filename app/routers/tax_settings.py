"""Эндпоинты для налоговых настроек селлера."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import TaxSettings, User
from app.schemas import TaxSettingsRead, TaxSettingsUpsert

router = APIRouter(prefix="/tax-settings", tags=["tax-settings"])

VALID_TAX_SYSTEMS = {"NPD", "USN_INCOME", "USN_INCOME_EXPENSE", "PSN"}


@router.get("", response_model=TaxSettingsRead | None)
async def get_tax_settings(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TaxSettings | None:
    """Получить текущие налоговые настройки. Если не заданы — вернёт null."""
    stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    return (await session.execute(stmt)).scalar_one_or_none()


@router.put("", response_model=TaxSettingsRead)
async def upsert_tax_settings(
    payload: TaxSettingsUpsert,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TaxSettings:
    """Создать или обновить налоговые настройки (upsert)."""
    if payload.tax_system not in VALID_TAX_SYSTEMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tax_system must be one of {sorted(VALID_TAX_SYSTEMS)}",
        )
    if payload.tax_rate < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tax_rate must be >= 0",
        )

    stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    settings = (await session.execute(stmt)).scalar_one_or_none()

    if settings is None:
        settings = TaxSettings(
            user_id=current_user.id,
            tax_system=payload.tax_system,
            tax_rate=payload.tax_rate,
            insurance_contributions=payload.insurance_contributions,
            vat_enabled=payload.vat_enabled,
            vat_rate=payload.vat_rate,
        )
        session.add(settings)
    else:
        settings.tax_system = payload.tax_system
        settings.tax_rate = payload.tax_rate
        settings.insurance_contributions = payload.insurance_contributions
        settings.vat_enabled = payload.vat_enabled
        settings.vat_rate = payload.vat_rate

    await session.commit()
    await session.refresh(settings)
    return settings


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tax_settings(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Удалить налоговые настройки."""
    stmt = select(TaxSettings).where(TaxSettings.user_id == current_user.id)
    settings = (await session.execute(stmt)).scalar_one_or_none()
    if settings is not None:
        await session.delete(settings)
        await session.commit()
