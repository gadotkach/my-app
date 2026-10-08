"""Эндпоинты для Ozon Ads (Performance API)."""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.deps import get_session, require_active_subscription
from app.models import OzonAdsAccount, User
from app.ozon_ads_client import OzonAdsClient, OzonAdsClientError
from app.schemas import OzonAdsAccountRead, OzonAdsConnect, OzonAdsSyncResult
from app.services.ozon_ads_sync import sync_ozon_ads

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/ozon-ads", tags=["ozon-ads"])


@router.post(
    "/connect",
    response_model=OzonAdsAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_ozon_ads(
    payload: OzonAdsConnect,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> OzonAdsAccountRead:
    """Подключить Ozon Ads: сохранить client_id + client_secret (зашифрован)."""
    try:
        async with OzonAdsClient(payload.client_id, payload.client_secret) as client:
            ok = await client.verify_credentials()
    except OzonAdsClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ozon Ads: не удалось авторизоваться",
        )

    existing = await session.scalar(
        select(OzonAdsAccount).where(OzonAdsAccount.user_id == current_user.id)
    )

    if existing is not None:
        existing.client_id = payload.client_id
        existing.client_secret_encrypted = encrypt(payload.client_secret)
        await session.commit()
        await session.refresh(existing)
        account = existing
    else:
        account = OzonAdsAccount(
            user_id=current_user.id,
            client_id=payload.client_id,
            client_secret_encrypted=encrypt(payload.client_secret),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)

    return OzonAdsAccountRead(
        id=account.id,
        client_id=account.client_id,
        last_sync_at=account.last_sync_at,
        created_at=account.created_at,
    )


@router.get("/account", response_model=OzonAdsAccountRead)
async def get_ozon_ads_account(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> OzonAdsAccountRead:
    """Получить информацию о подключённом Ozon Ads-аккаунте."""
    account = await session.scalar(
        select(OzonAdsAccount).where(OzonAdsAccount.user_id == current_user.id)
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ozon Ads is not connected",
        )
    return OzonAdsAccountRead(
        id=account.id,
        client_id=account.client_id,
        last_sync_at=account.last_sync_at,
        created_at=account.created_at,
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_ozon_ads(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Отключить Ozon Ads."""
    account = await session.scalar(
        select(OzonAdsAccount).where(OzonAdsAccount.user_id == current_user.id)
    )
    if account is not None:
        await session.delete(account)
        await session.commit()


@router.post("/sync", response_model=OzonAdsSyncResult)
async def sync_ozon_ads_endpoint(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> OzonAdsSyncResult:
    """Синхронизировать расходы Ozon Ads за период."""
    account = await session.scalar(
        select(OzonAdsAccount).where(OzonAdsAccount.user_id == current_user.id)
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ozon Ads is not connected",
        )

    client_secret = decrypt(account.client_secret_encrypted)

    result = await sync_ozon_ads(
        user_id=current_user.id,
        client_id=account.client_id,
        client_secret=client_secret,
        date_from=from_date,
        date_to=to_date,
    )

    account.last_sync_at = datetime.now(UTC)
    await session.commit()

    return OzonAdsSyncResult(**result)
