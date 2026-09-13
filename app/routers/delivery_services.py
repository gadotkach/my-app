from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import DeliveryService, User
from app.schemas import DeliveryServiceCreate, DeliveryServiceRead

router = APIRouter(prefix="/delivery-services", tags=["delivery-services"])


@router.get("", response_model=list[DeliveryServiceRead])
async def list_delivery_services(
    session: AsyncSession = Depends(get_session),
) -> list[DeliveryService]:
    result = await session.scalars(select(DeliveryService).order_by(DeliveryService.id))
    return list(result.all())


@router.post("", response_model=DeliveryServiceRead, status_code=status.HTTP_201_CREATED)
async def create_delivery_service(
    payload: DeliveryServiceCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeliveryService:
    existing = await session.scalar(
        select(DeliveryService).where(DeliveryService.code == payload.code)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Delivery service with code '{payload.code}' already exists",
        )
    service = DeliveryService(code=payload.code, name=payload.name)
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service
