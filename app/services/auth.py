"""
Auth Service — JWT-based authentication for operators.

- Passwords hashed with bcrypt (passlib)
- Tokens signed with HS256 (python-jose)
- 24-hour token expiry by default
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger
from app.storage.database import AsyncSessionLocal
from app.storage.models import UserRecord
from sqlmodel import select

logger = get_logger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _pwd.hash(plain[:72])


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain[:72], hashed)


# ── Token helpers ─────────────────────────────────────────────────────────────

class TokenData(BaseModel):
    user_id: int
    email: str


def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "email": email, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
        email: str = payload["email"]
        return TokenData(user_id=user_id, email=email)
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_user_by_email(email: str) -> Optional[UserRecord]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserRecord).where(UserRecord.email == email))
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: int) -> Optional[UserRecord]:
    async with AsyncSessionLocal() as session:
        return await session.get(UserRecord, user_id)


async def create_user(email: str, password: str) -> UserRecord:
    existing = await get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    async with AsyncSessionLocal() as session:
        user = UserRecord(email=email, hashed_password=hash_password(password))
        session.add(user)
        await session.commit()
        await session.refresh(user)
    logger.info("auth.user_created", email=email)
    return user


async def authenticate_user(email: str, password: str) -> UserRecord:
    user = await get_user_by_email(email)
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    return user
