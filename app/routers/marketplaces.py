from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.marketplaces import MarketplaceRegistry
from app.models import Marketplace, User
from app.schemas import MarketplaceCreate, MarketplaceRead, MarketplaceWithMeta

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])


@router.get("", response_model=list[MarketplaceWithMeta])
async def list_marketplaces(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Список МП с полями для UI (генерация форм)."""
    result = await session.scalars(select(Marketplace).order_by(Marketplace.id))
    rows = list(result.all())

    registry = MarketplaceRegistry.all()

    out: list[dict[str, Any]] = []
    for m in rows:
        cls = registry.get(m.code)
        if cls is not None:
            out.append(
                {
                    "id": m.id,
                    "code": m.code,
                    "name": m.name,
                    "auth_fields": cls.auth_fields,
                    "has_products": cls.has_products,
                    "has_sales": cls.has_sales,
                    "has_ads": cls.has_ads,
                }
            )
        else:
            # МП без клиента (Яндекс, Мегамаркет — пока нет)
            out.append(
                {
                    "id": m.id,
                    "code": m.code,
                    "name": m.name,
                    "auth_fields": [],
                    "has_products": False,
                    "has_sales": False,
                    "has_ads": False,
                }
            )
    return out


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
