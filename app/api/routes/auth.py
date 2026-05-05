"""
Auth endpoints.

POST /api/v1/auth/signup   Register a new operator account
POST /api/v1/auth/token    Login — returns JWT access token
GET  /api/v1/auth/me       Get current user info
"""

import re
from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, field_validator

from app.services.auth import create_user, authenticate_user, create_access_token
from app.api.dependencies import get_current_user
from app.storage.models import UserRecord

router = APIRouter(prefix="/auth", tags=["auth"])

_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&_\-#])[A-Za-z\d@$!%*?&_\-#]{8,}$")


class SignupRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        if not _PASSWORD_RE.match(v):
            raise ValueError(
                "Password must be at least 8 characters and include "
                "uppercase, lowercase, digit, and special character (@$!%*?&_-#)"
            )
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


class UserResponse(BaseModel):
    user_id: int
    email: str
    is_active: bool


@router.post("/signup", response_model=UserResponse, status_code=201)
async def signup(body: SignupRequest) -> UserResponse:
    """Register a new operator account."""
    user = await create_user(body.email, body.password)
    return UserResponse(user_id=user.id, email=user.email, is_active=user.is_active)


@router.post("/token", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """Login with email + password. Returns a JWT access token."""
    user = await authenticate_user(form.username, form.password)
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user_id=user.id, email=user.email)


@router.get("/me", response_model=UserResponse)
async def me(current_user: UserRecord = Depends(get_current_user)) -> UserResponse:
    """Get current authenticated user."""
    return UserResponse(user_id=current_user.id, email=current_user.email, is_active=current_user.is_active)
