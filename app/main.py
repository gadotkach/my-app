import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine
from app.routers import (
    analytics,
    auth,
    delivery_services,
    integrations,
    marketplaces,
    products,
    sales,
    subscriptions,
    users,
)
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("APP BUILD marker-v2 — require_active_subscription enabled")
logger = logging.getLogger(__name__)
logger.info("APP BUILD 9271999 — require_active_subscription enabled")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="My App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "https://my-app-frontend-biz.pages.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(subscriptions.router)
app.include_router(marketplaces.router)
app.include_router(delivery_services.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(analytics.router)
app.include_router(integrations.router)


@app.get("/health")
async def health() -> dict[str, object]:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        db_ok = result.scalar() == 1
    return {"status": "ok", "db": db_ok}
