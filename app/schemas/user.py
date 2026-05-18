"""Shared user identifier type — UUID string (RFC 4122)."""

from __future__ import annotations

import uuid

UserId = str


def normalize_user_uuid(value: str) -> UserId:
    """Parse and canonicalize a user UUID string."""
    return str(uuid.UUID(str(value).strip()))


def new_user_uuid() -> UserId:
    return str(uuid.uuid4())
