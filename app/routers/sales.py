from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import DeliveryService, Marketplace, Sale, User
from app.schemas import SaleCreate, SaleRead

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("", response_model=SaleRead, status_code=status.HTTP_201_CREATED)
async def create_sale(
    payload: SaleCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Sale:
    marketplace = await session.scalar(
        select(Marketplace).where(Marketplace.code == payload.marketplace_code)
    )
    if marketplace is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown marketplace code: {payload.marketplace_code}",
        )

    delivery_service_id: int | None = None
    if payload.delivery_service_code is not None:
        delivery_service = await session.scalar(
            select(DeliveryService).where(DeliveryService.code == payload.delivery_service_code)
        )
        if delivery_service is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown delivery service code: {payload.delivery_service_code}",
            )
        delivery_service_id = delivery_service.id

    sale = Sale(
        user_id=current_user.id,
        marketplace_id=marketplace.id,
        product_id=payload.product_id,
        delivery_service_id=delivery_service_id,
        external_id=payload.external_id,
        quantity=payload.quantity,
        price=payload.price,
        commission=payload.commission,
        logistics_cost=payload.logistics_cost,
        sold_at=payload.sold_at,
    )
    session.add(sale)
    await session.commit()
    await session.refresh(sale)
    return sale


@router.get("", response_model=list[SaleRead])
async def list_sales(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Sale]:
    result = await session.scalars(
        select(Sale).where(Sale.user_id == current_user.id).order_by(Sale.sold_at.desc())
    )
    return list(result.all())
