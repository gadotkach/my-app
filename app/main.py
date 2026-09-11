from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine

app = FastAPI(title="My App")


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        db_ok = result.scalar() == 1
    return {"status": "ok", "db": db_ok}
