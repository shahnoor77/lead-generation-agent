"""
Auth endpoints.

GET  /api/v1/auth/me   Validate (or self-register) UUID + API key and return user info
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.storage.models import UserRecord

router = APIRouter(prefix="/auth", tags=["auth"])


class UserResponse(BaseModel):
    user_id: str
    email: str | None = None
    is_active: bool


@router.get("/me", response_model=UserResponse)
async def me(current_user: UserRecord = Depends(get_current_user)) -> UserResponse:
    """Validate credentials; creates account on first use of a new UUID when self-registration is enabled."""
    return UserResponse(
        user_id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
    )
