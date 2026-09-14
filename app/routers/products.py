from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session, require_active_subscription
from app.models import Product, User
from app.schemas import ProductCreate, ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> Product:
    product = Product(user_id=current_user.id, **payload.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.get("", response_model=list[ProductRead])
async def list_products(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> list[Product]:
    result = await session.scalars(
        select(Product).where(Product.user_id == current_user.id).order_by(Product.id)
    )
    return list(result.all())


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: int,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_session),
) -> Product:
    product = await session.get(Product, product_id)
    if product is None or product.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product
