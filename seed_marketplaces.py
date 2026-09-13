"""Seed marketplaces and delivery services. Run once:
docker compose run --rm api python seed_marketplaces.py
"""

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import DeliveryService, Marketplace

MARKETPLACES = [
    {"code": "ozon", "name": "Ozon"},
    {"code": "wildberries", "name": "Wildberries"},
    {"code": "yandex_market", "name": "Яндекс.Маркет"},
    {"code": "aliexpress", "name": "AliExpress"},
    {"code": "avito", "name": "Авито"},
]

DELIVERY_SERVICES = [
    {"code": "cdek", "name": "СДЭК"},
    {"code": "boxberry", "name": "Boxberry"},
    {"code": "russian_post", "name": "Почта России"},
    {"code": "dhl", "name": "DHL"},
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for data in MARKETPLACES:
            existing = await session.scalar(
                select(Marketplace).where(Marketplace.code == data["code"])
            )
            if existing is None:
                session.add(Marketplace(**data))
                print(f"Added marketplace: {data['code']}")
            else:
                print(f"Skipped (exists): {data['code']}")

        for data in DELIVERY_SERVICES:
            existing = await session.scalar(
                select(DeliveryService).where(DeliveryService.code == data["code"])
            )
            if existing is None:
                session.add(DeliveryService(**data))
                print(f"Added delivery: {data['code']}")
            else:
                print(f"Skipped (exists): {data['code']}")

        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
