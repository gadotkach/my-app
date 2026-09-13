from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine
from app.routers import auth, delivery_services, marketplaces, products, sales, users

app = FastAPI(title="My App")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(marketplaces.router)
app.include_router(delivery_services.router)
app.include_router(products.router)
app.include_router(sales.router)


@app.get("/health")
async def health() -> dict[str, object]:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        db_ok = result.scalar() == 1
    return {"status": "ok", "db": db_ok}
