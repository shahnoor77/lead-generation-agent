"""
Webhook Service — dispatch event payloads to registered subscriber URLs.

Architecture:
  - WebhookSubscriptionRecord stores per-user subscriptions (url, events)
  - dispatch() is called at every key event point in the pipeline/lifecycle/outreach
  - Delivery is fire-and-forget (background task) — never blocks the main request
  - Failed deliveries are retried up to 3 times with exponential backoff (tenacity)

Supported events:
  run.completed           — pipeline run finished
  lead.status_changed     — any lifecycle status transition
  lead.discovered         — new lead found by discovery
  lead.qualified          — lead passed ICP evaluation
  lead.outreach_drafted   — outreach email draft generated
  outreach.sent           — email sent to a lead
  outreach.replied        — prospect replied to an email
  outreach.meeting        — meeting handoff created
  draft.finalized         — human finalized a draft
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlmodel import select

from app.storage.database import AsyncSessionLocal
from app.storage.models import WebhookSubscriptionRecord
from app.core.logging import get_logger

logger = get_logger(__name__)

# All valid event types — clients subscribe to one or more of these
WEBHOOK_EVENTS = {
    "run.completed",
    "lead.status_changed",
    "lead.discovered",
    "lead.qualified",
    "lead.outreach_drafted",
    "outreach.sent",
    "outreach.replied",
    "outreach.meeting",
    "draft.finalized",
}


def _build_envelope(event: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event,
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "user_id": user_id,
        "data": data,
    }


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=False,
)
async def _deliver(client: httpx.AsyncClient, url: str, body: bytes, event: str) -> None:
    """Single delivery attempt — retried on network errors."""
    resp = await client.post(
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Event": event,
            "User-Agent": "LeadGen-Webhook/1.0",
        },
        timeout=10.0,
    )
    if resp.status_code >= 400:
        logger.warning(
            "webhook.delivery_failed",
            url=url,
            event=event,
            status=resp.status_code,
        )
    else:
        logger.info("webhook.delivered", url=url, event=event, status=resp.status_code)


async def _dispatch_to_subscriber(
    sub: WebhookSubscriptionRecord,
    event: str,
    body: bytes,
) -> None:
    """Fire one webhook delivery — errors are caught and logged, never raised."""
    try:
        async with httpx.AsyncClient() as client:
            await _deliver(client, sub.url, body, event)
    except Exception as exc:
        logger.error(
            "webhook.dispatch_error",
            url=sub.url,
            event=event,
            error=str(exc)[:200],
        )


async def dispatch(event: str, user_id: str, data: dict[str, Any]) -> None:
    """
    Look up all active subscriptions for this user+event and fire them concurrently.
    Called from pipeline, lifecycle, outreach — always fire-and-forget.
    """
    if event not in WEBHOOK_EVENTS:
        logger.warning("webhook.unknown_event", event=event)
        return

    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(WebhookSubscriptionRecord)
                .where(WebhookSubscriptionRecord.user_id == user_id)
                .where(WebhookSubscriptionRecord.is_active == True)
            )
            result = await session.execute(stmt)
            subs = result.scalars().all()
    except Exception as exc:
        logger.error("webhook.db_lookup_failed", event=event, error=str(exc)[:200])
        return

    # Filter to subscribers that want this event
    matching = [s for s in subs if event in json.loads(s.events or "[]")]
    if not matching:
        return

    envelope = _build_envelope(event, user_id, data)
    body = json.dumps(envelope, default=str).encode()

    tasks = [asyncio.create_task(_dispatch_to_subscriber(sub, event, body)) for sub in matching]
    logger.info("webhook.dispatching", event=event, user_id=user_id, subscribers=len(tasks))


def fire_and_forget(event: str, user_id: str | None, data: dict[str, Any]) -> None:
    """
    Synchronous entry point — schedules dispatch as a background asyncio task.
    Safe to call from anywhere (pipeline, services, agents).
    Silently skips if user_id is None.
    """
    if not user_id:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(dispatch(event, user_id, data))
    except Exception as exc:
        logger.error("webhook.fire_and_forget_error", event=event, error=str(exc)[:200])
