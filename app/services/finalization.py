"""
Draft Finalization Service — Chunk 2

Handles the human review layer between generated draft and final draft.

Rules enforced here:
- Generated draft is NEVER overwritten (read from outreach_drafts, copied once)
- Final draft is always editable (re-calling finalize-draft updates it)
- approval_status is always "PENDING_REVIEW" after finalization
- System never sets approval_status = "APPROVED"
- Finalizing always moves lifecycle to READY_FOR_REVIEW
"""

from __future__ import annotations
from datetime import datetime
from fastapi import HTTPException

from app.schemas.finalization import (
    FinalizeDraftRequest,
    FinalizeDraftResponse,
    ReceiverDetails,
    SenderDetails,
)
from app.schemas.lifecycle import LeadLifecycleStatus
from app.storage.models import FinalizedDraftRecord, OutreachRecord
from app.storage.database import AsyncSessionLocal
from app.services.lifecycle import LeadLifecycleService
from app.core.logging import get_logger
from sqlmodel import select

logger = get_logger(__name__)
_lifecycle = LeadLifecycleService()


def _now() -> datetime:
    return datetime.utcnow()


class DraftFinalizationService:

    async def finalize(
        self,
        lead_id: str,
        payload: FinalizeDraftRequest,
    ) -> FinalizeDraftResponse:
        """
        Save the human-edited final draft alongside the original generated draft.

        - Looks up the original generated draft from outreach_drafts.
        - Creates or updates a row in finalized_drafts.
        - Generated draft fields are copied once and never changed again.
        - Final draft fields are always overwritten (editable).
        - Moves lifecycle status to READY_FOR_REVIEW.
        - approval_status is always reset to PENDING_REVIEW on every finalize call.
        """
        # ── Fetch original generated draft ────────────────────────────────────
        generated = await self._get_generated_draft(lead_id)
        if generated is None:
            raise HTTPException(
                status_code=404,
                detail=f"No generated draft found for lead {lead_id}. "
                       "The pipeline must complete outreach generation first.",
            )

        now = _now()

        async with AsyncSessionLocal() as session:
            existing = await session.get(FinalizedDraftRecord, lead_id)

            if existing:
                # Update final draft fields — generated fields stay untouched
                existing.final_subject = payload.final_subject
                existing.final_body = payload.final_body
                existing.finalized_at = now
                existing.finalized_by = payload.finalized_by
                existing.notes = payload.notes
                # Receiver
                existing.receiver_name = payload.receiver_details.receiver_name
                existing.receiver_role = payload.receiver_details.receiver_role
                existing.receiver_email = str(payload.receiver_details.receiver_email)
                existing.receiver_linkedin_url = payload.receiver_details.linkedin_url
                existing.preferred_contact_method = payload.receiver_details.preferred_contact_method or "email"
                # Sender
                existing.sender_name = payload.sender_details.sender_name
                existing.sender_role = payload.sender_details.sender_role
                existing.sender_company = payload.sender_details.sender_company
                existing.sender_email = str(payload.sender_details.sender_email)
                existing.sender_phone = payload.sender_details.sender_phone
                existing.signature = payload.sender_details.signature
                # Reset approval — re-finalization requires re-approval
                existing.approval_status = "PENDING_REVIEW"
                existing.approved_by = None
                existing.approved_at = None
                session.add(existing)
                record = existing
            else:
                record = FinalizedDraftRecord(
                    lead_id=lead_id,
                    pipeline_run_id=generated.pipeline_run_id,
                    company_name=generated.lead_id,  # will be overridden below
                    # Generated draft — copied once, never changed
                    generated_subject=generated.email_subject,
                    generated_body=generated.email_body,
                    generated_at=generated.generated_at,
                    # Final draft
                    final_subject=payload.final_subject,
                    final_body=payload.final_body,
                    finalized_at=now,
                    finalized_by=payload.finalized_by,
                    notes=payload.notes,
                    # Receiver
                    receiver_name=payload.receiver_details.receiver_name,
                    receiver_role=payload.receiver_details.receiver_role,
                    receiver_email=str(payload.receiver_details.receiver_email),
                    receiver_linkedin_url=payload.receiver_details.linkedin_url,
                    preferred_contact_method=payload.receiver_details.preferred_contact_method or "email",
                    # Sender
                    sender_name=payload.sender_details.sender_name,
                    sender_role=payload.sender_details.sender_role,
                    sender_company=payload.sender_details.sender_company,
                    sender_email=str(payload.sender_details.sender_email),
                    sender_phone=payload.sender_details.sender_phone,
                    signature=payload.sender_details.signature,
                    # Approval — always starts as PENDING_REVIEW
                    approval_status="PENDING_REVIEW",
                )
                session.add(record)

            await session.commit()
            await session.refresh(record)

        # ── Resolve company name from lifecycle ────────────────────────────────
        company_name = await self._get_company_name(lead_id)

        # ── Update lifecycle → READY_FOR_REVIEW ───────────────────────────────
        # Use internal upsert — bypass transition validation since this is
        # a controlled finalization action, not a free-form status change.
        await _lifecycle._upsert(
            lead_id=lead_id,
            company_name=company_name,
            pipeline_run_id=generated.pipeline_run_id,
            status=LeadLifecycleStatus.READY_FOR_REVIEW,
            changed_by=payload.finalized_by or "operator",
            notes="Draft finalized",
        )

        logger.info(
            "finalization.draft_finalized",
            lead_id=lead_id,
            finalized_by=payload.finalized_by,
        )

        return FinalizeDraftResponse(
            lead_id=lead_id,
            company_name=company_name,
            generated_subject=record.generated_subject,
            generated_body=record.generated_body,
            generated_at=record.generated_at,
            final_subject=record.final_subject,
            final_body=record.final_body,
            finalized_at=record.finalized_at,
            finalized_by=record.finalized_by,
            receiver_details=ReceiverDetails(
                receiver_name=record.receiver_name,
                receiver_role=record.receiver_role,
                receiver_email=record.receiver_email,
                linkedin_url=record.receiver_linkedin_url,
                preferred_contact_method=record.preferred_contact_method,
            ),
            sender_details=SenderDetails(
                sender_name=record.sender_name,
                sender_role=record.sender_role,
                sender_company=record.sender_company,
                sender_email=record.sender_email,
                sender_phone=record.sender_phone,
                signature=record.signature,
            ),
            approval_status=record.approval_status,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            lifecycle_status=LeadLifecycleStatus.READY_FOR_REVIEW.value,
        )

    async def get_finalized_draft(self, lead_id: str) -> FinalizeDraftResponse:
        """Retrieve the current finalized draft for a lead."""
        async with AsyncSessionLocal() as session:
            record = await session.get(FinalizedDraftRecord, lead_id)

        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"No finalized draft found for lead {lead_id}",
            )

        company_name = await self._get_company_name(lead_id)

        return FinalizeDraftResponse(
            lead_id=lead_id,
            company_name=company_name,
            generated_subject=record.generated_subject,
            generated_body=record.generated_body,
            generated_at=record.generated_at,
            final_subject=record.final_subject,
            final_body=record.final_body,
            finalized_at=record.finalized_at,
            finalized_by=record.finalized_by,
            receiver_details=ReceiverDetails(
                receiver_name=record.receiver_name,
                receiver_role=record.receiver_role,
                receiver_email=record.receiver_email,
                linkedin_url=record.receiver_linkedin_url,
                preferred_contact_method=record.preferred_contact_method,
            ),
            sender_details=SenderDetails(
                sender_name=record.sender_name,
                sender_role=record.sender_role,
                sender_company=record.sender_company,
                sender_email=record.sender_email,
                sender_phone=record.sender_phone,
                signature=record.signature,
            ),
            approval_status=record.approval_status,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            lifecycle_status=LeadLifecycleStatus.READY_FOR_REVIEW.value,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_generated_draft(self, lead_id: str) -> OutreachRecord | None:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(OutreachRecord)
                .where(OutreachRecord.lead_id == lead_id)
                .order_by(OutreachRecord.generated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def _get_company_name(self, lead_id: str) -> str:
        from app.storage.models import LeadLifecycleRecord
        async with AsyncSessionLocal() as session:
            lc = await session.get(LeadLifecycleRecord, lead_id)
            return lc.company_name if lc else lead_id
