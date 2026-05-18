"""
Auth Service — shared operator API key (from .env) + per-user UUID.

Self-registration (when enabled):
  - Valid OPERATOR_API_KEY + new UUID → creates that user.
  - Valid OPERATOR_API_KEY + existing UUID → authenticates.

Admin CLI (scripts/create_api_user.py) pre-provisions a UUID; same shared API key applies.
"""

from __future__ import annotations

import secrets
from typing import Optional

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.user import UserId, normalize_user_uuid, new_user_uuid
from app.storage.database import AsyncSessionLocal
from app.storage.models import UserRecord

logger = get_logger(__name__)


def hash_api_key(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify_operator_api_key(api_key: str) -> None:
    """Reject unless the client key matches OPERATOR_API_KEY from .env."""
    expected = (settings.operator_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server operator API key is not configured",
        )
    provided = (api_key or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user UUID or API key",
        )


async def get_user_by_id(user_id: UserId) -> Optional[UserRecord]:
    async with AsyncSessionLocal() as session:
        return await session.get(UserRecord, normalize_user_uuid(user_id))


async def _register_user(uid: str) -> UserRecord:
    """Persist a new user for a client-supplied UUID."""
    user = UserRecord(
        id=uid,
        email=None,
        api_key_hash=hash_api_key(settings.operator_api_key),
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(user)
        try:
            await session.commit()
            await session.refresh(user)
        except IntegrityError:
            await session.rollback()
            existing = await get_user_by_id(uid)
            if existing:
                return existing
            raise
    logger.info("auth.user_self_registered", user_id=uid)
    return user


async def authenticate_or_register_user(user_id: str, api_key: str) -> UserRecord:
    """
    Authenticate an existing user, or self-register on first use of a UUID.

    API key must match OPERATOR_API_KEY in server .env (shared secret).
    """
    _verify_operator_api_key(api_key)
    uid = normalize_user_uuid(user_id)

    user = await get_user_by_id(uid)
    if user:
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")
        return user

    if not settings.allow_user_self_registration:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Self-registration is disabled.",
        )

    return await _register_user(uid)


async def authenticate_api_key(user_id: str, api_key: str) -> UserRecord:
    """Strict auth only — never creates users."""
    _verify_operator_api_key(api_key)
    uid = normalize_user_uuid(user_id)
    user = await get_user_by_id(uid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user UUID or API key",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


async def provision_user(*, email: str | None = None) -> UserRecord:
    """
    Admin CLI: create a user with server-generated UUID.
    Authentication uses OPERATOR_API_KEY from .env (not per-user keys).
    """
    if not (settings.operator_api_key or "").strip():
        raise RuntimeError("Set OPERATOR_API_KEY in .env before provisioning users")

    user = UserRecord(
        id=new_user_uuid(),
        email=email.strip().lower() if email else None,
        api_key_hash=hash_api_key(settings.operator_api_key),
        is_active=True,
    )
    async with AsyncSessionLocal() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    logger.info("auth.user_provisioned", user_id=user.id, email=user.email)
    return user
