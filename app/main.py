from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import health, leads
from app.core.logging import setup_logging
from app.storage.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    yield


app = FastAPI(
    title="KSA Lead Generation System",
    description="Phase 1 — Precision B2B lead generation for KSA Business Transformation Consulting",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health.router, tags=["health"])
app.include_router(leads.router, prefix="/api/v1", tags=["leads"])
