import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api.routes import health, leads
from app.api.routes import lifecycle
from app.api.routes import finalization
from app.api.routes import operations
from app.api.routes import auth
from app.api.routes import settings as settings_router
from app.api.routes import outreach_agent
from app.api.routes import webhooks as webhooks_router
from app.core.config import _ENV_FILE, settings
from app.core.logging import get_logger, setup_logging
from app.storage.database import init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    key_set = bool((settings.operator_api_key or "").strip())
    logger.info(
        "app.startup",
        env_file=str(_ENV_FILE),
        env_file_exists=_ENV_FILE.is_file(),
        operator_api_key_configured=key_set,
        self_registration=settings.allow_user_self_registration,
    )
    if not key_set:
        logger.warning("app.startup.operator_api_key_missing — set OPERATOR_API_KEY in .env and restart")
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


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=ms,
    )
    return response


app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(leads.router, prefix="/api/v1", tags=["leads"])
app.include_router(lifecycle.router, prefix="/api/v1", tags=["lifecycle"])
app.include_router(finalization.router, prefix="/api/v1", tags=["finalization"])
app.include_router(operations.router, prefix="/api/v1", tags=["operations"])
app.include_router(settings_router.router, prefix="/api/v1", tags=["settings"])
app.include_router(outreach_agent.router, prefix="/api/v1", tags=["outreach-agent"])
app.include_router(webhooks_router.router, prefix="/api/v1", tags=["webhooks"])
