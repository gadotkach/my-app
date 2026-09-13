from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt
from app.deps import get_current_user, get_session
from app.models import Marketplace, MarketplaceAccount, User
from app.ozon_client import OzonClient, OzonClientError
from app.schemas import MarketplaceAccountConnect, MarketplaceAccountRead

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post(
    "/ozon/connect",
    response_model=MarketplaceAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_ozon(
    payload: MarketplaceAccountConnect,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MarketplaceAccountRead:
    if payload.marketplace_code != "ozon":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint supports only marketplace_code='ozon'",
        )

    marketplace = await session.scalar(
        select(Marketplace).where(Marketplace.code == payload.marketplace_code)
    )
    if marketplace is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Marketplace 'ozon' not found in database",
        )

    # Проверяем ключи через реальный API Ozon
    try:
        async with OzonClient(payload.client_id, payload.api_key) as ozon:
            seller_info = await ozon.get_seller_info()
    except OzonClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Если у пользователя уже был подключён Ozon — обновляем ключи
    existing = await session.scalar(
        select(MarketplaceAccount).where(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace_id == marketplace.id,
        )
    )

    if existing is not None:
        existing.client_id = payload.client_id
        existing.api_key_encrypted = encrypt(payload.api_key)
        await session.commit()
        await session.refresh(existing)
        account = existing
    else:
        account = MarketplaceAccount(
            user_id=current_user.id,
            marketplace_id=marketplace.id,
            client_id=payload.client_id,
            api_key_encrypted=encrypt(payload.api_key),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)

    company = seller_info.get("company", {}) if isinstance(seller_info, dict) else {}
    return MarketplaceAccountRead(
        id=account.id,
        marketplace_code=marketplace.code,
        client_id=account.client_id,
        created_at=account.created_at,
    )


@router.get("/accounts", response_model=list[MarketplaceAccountRead])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MarketplaceAccountRead]:
    stmt = (
        select(MarketplaceAccount, Marketplace.code)
        .join(Marketplace, MarketplaceAccount.marketplace_id == Marketplace.id)
        .where(MarketplaceAccount.user_id == current_user.id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MarketplaceAccountRead(
            id=account.id,
            marketplace_code=code,
            client_id=account.client_id,
            created_at=account.created_at,
        )
        for account, code in rows
    ]
