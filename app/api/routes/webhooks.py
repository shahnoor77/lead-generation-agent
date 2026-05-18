"""
Webhook subscription management.

POST   /api/v1/webhooks          — register a new webhook URL
GET    /api/v1/webhooks          — list all registered webhooks for this user
GET    /api/v1/webhooks/{id}     — get a single subscription
PATCH  /api/v1/webhooks/{id}     — update url / events / active state
DELETE /api/v1/webhooks/{id}     — remove a subscription
GET    /api/v1/webhooks/events   — list all supported event types

Payload for POST / PATCH:
  {
    "url": "https://yourapp.com/hooks/leadgen",
    "events": ["run.completed", "lead.status_changed"],
    "description": "optional label"
  }

Outgoing webhook format (POST to your URL):
  {
    "event": "run.completed",
    "event_id": "<uuid>",
    "timestamp": "2026-05-18T10:30:00Z",
    "user_id": "<your-uuid>",
    "data": { ... event-specific fields ... }
  }

Headers sent with every delivery:
  Content-Type: application/json
  X-Webhook-Event: <event-type>
  User-Agent: LeadGen-Webhook/1.0
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl, field_validator
from sqlmodel import select

from app.api.dependencies import get_current_user
from app.services.webhooks import WEBHOOK_EVENTS
from app.storage.database import AsyncSessionLocal
from app.storage.models import UserRecord, WebhookSubscriptionRecord

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class WebhookCreateRequest(BaseModel):
    url: HttpUrl
    events: list[str]
    description: Optional[str] = None

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: list[str]) -> list[str]:
        invalid = set(v) - WEBHOOK_EVENTS
        if invalid:
            raise ValueError(
                f"Unknown event types: {sorted(invalid)}. "
                f"Valid events: {sorted(WEBHOOK_EVENTS)}"
            )
        if not v:
            raise ValueError("events must contain at least one event type")
        return list(set(v))  # deduplicate


class WebhookUpdateRequest(BaseModel):
    url: Optional[HttpUrl] = None
    events: Optional[list[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        invalid = set(v) - WEBHOOK_EVENTS
        if invalid:
            raise ValueError(f"Unknown event types: {sorted(invalid)}")
        if not v:
            raise ValueError("events must contain at least one event type")
        return list(set(v))


class WebhookResponse(BaseModel):
    id: int
    user_id: str
    url: str
    events: list[str]
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


def _to_response(sub: WebhookSubscriptionRecord) -> WebhookResponse:
    return WebhookResponse(
        id=sub.id,
        user_id=sub.user_id,
        url=sub.url,
        events=json.loads(sub.events or "[]"),
        description=sub.description,
        is_active=sub.is_active,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/events", summary="List all supported webhook event types")
async def list_event_types() -> dict:
    """
    Returns all event types you can subscribe to, with descriptions.
    No authentication required.
    """
    return {
        "events": {
            "run.completed": "A pipeline run finished (discovery → enrichment → ICP → drafts)",
            "lead.status_changed": "Any lead lifecycle status transition (pipeline or human)",
            "lead.discovered": "A new lead was found by the discovery stage",
            "lead.qualified": "A lead passed ICP evaluation and is marked QUALIFIED",
            "lead.outreach_drafted": "An outreach email draft was generated for a lead",
            "outreach.sent": "An email was sent to a lead (initial or follow-up)",
            "outreach.replied": "A prospect replied to an outreach email",
            "outreach.meeting": "A meeting handoff was created from a positive reply",
            "draft.finalized": "A human finalized an outreach draft (READY_FOR_REVIEW)",
        }
    }


@router.post("", summary="Register a webhook URL", status_code=201)
async def create_webhook(
    payload: WebhookCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> WebhookResponse:
    """
    Register a URL to receive webhook events.

    - **url**: the endpoint on your server that will receive POST requests
    - **events**: list of event types to subscribe to (see GET /webhooks/events)
    - **description**: optional label for your reference

    You can register multiple webhooks (e.g. different URLs for different event groups).
    """
    now = datetime.utcnow()
    sub = WebhookSubscriptionRecord(
        user_id=current_user.id,
        url=str(payload.url),
        events=json.dumps(payload.events),
        description=payload.description,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    async with AsyncSessionLocal() as session:
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
    return _to_response(sub)


@router.get("", summary="List all registered webhooks")
async def list_webhooks(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """List all webhook subscriptions for the authenticated user."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(WebhookSubscriptionRecord)
            .where(WebhookSubscriptionRecord.user_id == current_user.id)
            .order_by(WebhookSubscriptionRecord.created_at.desc())
        )
        subs = result.scalars().all()
    return {
        "webhooks": [_to_response(s) for s in subs],
        "total": len(subs),
    }


@router.get("/{webhook_id}", summary="Get a single webhook subscription")
async def get_webhook(
    webhook_id: int,
    current_user: UserRecord = Depends(get_current_user),
) -> WebhookResponse:
    async with AsyncSessionLocal() as session:
        sub = await session.get(WebhookSubscriptionRecord, webhook_id)
    if not sub or sub.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return _to_response(sub)


@router.patch("/{webhook_id}", summary="Update a webhook subscription")
async def update_webhook(
    webhook_id: int,
    payload: WebhookUpdateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> WebhookResponse:
    """
    Update any field of a webhook subscription.
    Only provided fields are changed — omitted fields stay as-is.
    Set `is_active: false` to pause delivery without deleting the subscription.
    """
    async with AsyncSessionLocal() as session:
        sub = await session.get(WebhookSubscriptionRecord, webhook_id)
        if not sub or sub.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Webhook not found")

        if payload.url is not None:
            sub.url = str(payload.url)
        if payload.events is not None:
            sub.events = json.dumps(payload.events)
        if payload.description is not None:
            sub.description = payload.description
        if payload.is_active is not None:
            sub.is_active = payload.is_active

        sub.updated_at = datetime.utcnow()
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
    return _to_response(sub)


@router.delete("/{webhook_id}", summary="Delete a webhook subscription", status_code=204)
async def delete_webhook(
    webhook_id: int,
    current_user: UserRecord = Depends(get_current_user),
) -> None:
    """Permanently remove a webhook subscription."""
    async with AsyncSessionLocal() as session:
        sub = await session.get(WebhookSubscriptionRecord, webhook_id)
        if not sub or sub.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Webhook not found")
        await session.delete(sub)
        await session.commit()
