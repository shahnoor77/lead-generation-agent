"""
Sandbox / test outbound routing.

When ``sandbox_pipeline=True`` for a pipeline run, SMTP envelopes go to a user's
sandbox inbox addresses instead of real lead emails. Assignment is random on
first use and persisted per (user_id, lead_id) so two sandbox accounts never
split the same lead's thread.

Production runs (sandbox_pipeline=False) never read the map — envelopes always use natural emails.
"""

from __future__ import annotations

import secrets

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.storage.database import AsyncSessionLocal
from app.storage.models import (
    SandboxLeadRecipientMapRecord,
    SandboxTestInboxRecord,
    PipelineRunRecord,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class SandboxConfigError(RuntimeError):
    """No sandbox inboxes configured, or persistence failed."""

    pass


async def count_active_inboxes(user_id: str) -> int:
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(SandboxTestInboxRecord)
            .where(SandboxTestInboxRecord.user_id == user_id)
            .where(SandboxTestInboxRecord.is_active == True),  # noqa: E712
        )
        return len(list(r.scalars().all()))


async def resolve_smtp_receiver(
    user_id: str,
    lead_id: str,
    natural_email: str,
    *,
    sandbox_pipeline: bool,
) -> str:
    """
    Return the email address used for SMTP To: and outreach_sent receiver_email.

    - Production (sandbox_pipeline=False): always ``natural_email`` (no sandbox map lookups).
    - Sandbox pipeline: reuse persisted map row or randomly assign one active sandbox inbox,
      then persist.
    """
    ne = (natural_email or "").strip()
    if not sandbox_pipeline:
        return ne.lower() if ne else ne

    if not ne:
        raise SandboxConfigError("Cannot route sandbox outreach without a natural receiver email.")

    async with AsyncSessionLocal() as session:
        mapped = (
            (
                await session.execute(
                    select(SandboxLeadRecipientMapRecord).where(
                        SandboxLeadRecipientMapRecord.user_id == user_id,
                        SandboxLeadRecipientMapRecord.lead_id == lead_id,
                    )
                )
            )
            .scalar_one_or_none()
        )
        if mapped:
            return mapped.sandbox_email.strip().lower()

        inbox_rows = (
            (
                await session.execute(
                    select(SandboxTestInboxRecord)
                    .where(SandboxTestInboxRecord.user_id == user_id)
                    .where(SandboxTestInboxRecord.is_active == True),  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
        if not inbox_rows:
            raise SandboxConfigError(
                "No active sandbox test inboxes configured. Add at least one in Settings.",
            )

        picked = secrets.choice(inbox_rows)
        sandbox_addr = picked.email.strip().lower()
        session.add(
            SandboxLeadRecipientMapRecord(
                user_id=user_id,
                lead_id=lead_id,
                sandbox_email=sandbox_addr,
            )
        )
        try:
            await session.commit()
            logger.info("sandbox.mapping_created", user_id=user_id, lead_id=lead_id, to=sandbox_addr)
            return sandbox_addr
        except IntegrityError:
            await session.rollback()
            # Concurrent insert lost the race — re-read deterministic mapping
            again = (
                (
                    await session.execute(
                        select(SandboxLeadRecipientMapRecord).where(
                            SandboxLeadRecipientMapRecord.user_id == user_id,
                            SandboxLeadRecipientMapRecord.lead_id == lead_id,
                        )
                    )
                )
                .scalar_one_or_none()
            )
            if again:
                return again.sandbox_email.strip().lower()
            raise SandboxConfigError("Failed to persist sandbox recipient mapping.") from None


async def is_sandbox_pipeline_run(user_id: str, pipeline_run_id: str | None) -> bool:
    if not pipeline_run_id:
        return False
    async with AsyncSessionLocal() as session:
        row = await session.get(PipelineRunRecord, pipeline_run_id)
        if not row or row.user_id != user_id:
            return False
        return bool(getattr(row, "sandbox_outreach", False))
