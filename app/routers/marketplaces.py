from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import Marketplace, User
from app.schemas import MarketplaceCreate, MarketplaceRead

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])


@router.get("", response_model=list[MarketplaceRead])
async def list_marketplaces(session: AsyncSession = Depends(get_session)) -> list[Marketplace]:
    result = await session.scalars(select(Marketplace).order_by(Marketplace.id))
    return list(result.all())


@router.post("", response_model=MarketplaceRead, status_code=status.HTTP_201_CREATED)
async def create_marketplace(
    payload: MarketplaceCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Marketplace:
    existing = await session.scalar(select(Marketplace).where(Marketplace.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Marketplace with code '{payload.code}' already exists",
        )
    marketplace = Marketplace(code=payload.code, name=payload.name)
    session.add(marketplace)
    await session.commit()
    await session.refresh(marketplace)
    return marketplace
