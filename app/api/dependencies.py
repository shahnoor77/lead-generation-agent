"""FastAPI dependencies for auth."""

from fastapi import Depends, Header, HTTPException

from app.core.logging import get_logger
from app.services.auth import authenticate_or_register_user
from app.schemas.user import normalize_user_uuid
from app.storage.models import UserRecord

logger = get_logger(__name__)


async def get_current_user(
    x_user_id: str = Header(..., alias="X-User-Id", description="Operator UUID"),
    x_api_key: str = Header(..., alias="X-Api-Key", description="Operator API key"),
) -> UserRecord:
    if not x_user_id.strip() or not x_api_key.strip():
        logger.warning("auth.missing_headers")
        raise HTTPException(status_code=401, detail="Missing X-User-Id or X-Api-Key header")
    try:
        normalize_user_uuid(x_user_id)
    except ValueError as exc:
        logger.warning("auth.invalid_uuid_format", user_id_preview=x_user_id.strip()[:36])
        raise HTTPException(
            status_code=401,
            detail="Invalid user UUID format — use a full UUID like 550e8400-e29b-41d4-a716-446655440000",
        ) from exc
    try:
        user = await authenticate_or_register_user(x_user_id, x_api_key)
        logger.info("auth.ok", user_id=user.id)
        return user
    except HTTPException as exc:
        logger.warning("auth.failed", status=exc.status_code, detail=exc.detail)
        raise
