from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, leads
from app.api.routes import lifecycle
from app.api.routes import finalization
from app.api.routes import operations
from app.api.routes import auth
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(leads.router, prefix="/api/v1", tags=["leads"])
app.include_router(lifecycle.router, prefix="/api/v1", tags=["lifecycle"])
app.include_router(finalization.router, prefix="/api/v1", tags=["finalization"])
app.include_router(operations.router, prefix="/api/v1", tags=["operations"])
