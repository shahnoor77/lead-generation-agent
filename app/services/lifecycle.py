"""
Lead Lifecycle Service — Chunk 1

Handles all reads and writes for lead lifecycle state tracking.
Pipeline calls set_pipeline_status() automatically.
Humans call update_status() via the PATCH endpoint.
"""

from __future__ import annotations
from datetime import datetime
from fastapi import HTTPException

from app.schemas.lifecycle import (
    LeadLifecycleStatus,
    LeadStatusResponse,
    LeadStatusHistoryResponse,
    LeadStatusHistoryEntry,
    is_pipeline_status,
    is_valid_transition,
)
from app.storage.models import LeadLifecycleRecord, LeadLifecycleHistoryRecord
from app.storage.database import AsyncSessionLocal
from app.core.logging import get_logger
from sqlmodel import select

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.utcnow()


class LeadLifecycleService:

    # ── Pipeline calls this automatically ─────────────────────────────────────

    async def set_pipeline_status(
        self,
        lead_id: str,
        company_name: str,
        pipeline_run_id: str,
        status: LeadLifecycleStatus,
    ) -> None:
        """Called by the pipeline orchestrator — no transition validation needed."""
        await self._upsert(
            lead_id=lead_id,
            company_name=company_name,
            pipeline_run_id=pipeline_run_id,
            status=status,
            changed_by="pipeline",
            notes=None,
        )
        logger.info(
            "lifecycle.pipeline_status_set",
            lead_id=lead_id,
            status=status.value,
        )

    # ── Human calls this via PATCH endpoint ───────────────────────────────────

    async def update_status(
        self,
        lead_id: str,
        new_status: LeadLifecycleStatus,
        notes: str | None,
        updated_by: str | None,
    ) -> LeadStatusResponse:
        """
        Validates transition, updates current status, appends history.
        Raises 404 if lead not found, 422 if transition is invalid.
        """
        current = await self._get_current(lead_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found in lifecycle tracker")

        current_status = LeadLifecycleStatus(current.current_status)

        # Block humans from setting pipeline-only statuses
        if is_pipeline_status(new_status):
            raise HTTPException(
                status_code=422,
                detail=f"Status '{new_status.value}' is set automatically by the pipeline and cannot be set manually.",
            )

        # Validate transition
        if not is_valid_transition(current_status, new_status):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid transition: {current_status.value} → {new_status.value}",
            )

        await self._upsert(
            lead_id=lead_id,
            company_name=current.company_name,
            pipeline_run_id=current.pipeline_run_id,
            status=new_status,
            changed_by=updated_by or "human",
            notes=notes,
        )

        logger.info(
            "lifecycle.human_status_update",
            lead_id=lead_id,
            from_status=current_status.value,
            to_status=new_status.value,
            updated_by=updated_by,
        )

        return LeadStatusResponse(
            lead_id=lead_id,
            company_name=current.company_name,
            current_status=new_status,
            status_updated_at=_now(),
            updated_by=updated_by,
            notes=notes,
        )

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_status(self, lead_id: str) -> LeadStatusResponse:
        current = await self._get_current(lead_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
        return LeadStatusResponse(
            lead_id=lead_id,
            company_name=current.company_name,
            current_status=LeadLifecycleStatus(current.current_status),
            status_updated_at=current.status_updated_at,
            updated_by=current.updated_by,
            notes=current.notes,
        )

    async def get_history(self, lead_id: str) -> LeadStatusHistoryResponse:
        current = await self._get_current(lead_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

        async with AsyncSessionLocal() as session:
            stmt = (
                select(LeadLifecycleHistoryRecord)
                .where(LeadLifecycleHistoryRecord.lead_id == lead_id)
                .order_by(LeadLifecycleHistoryRecord.changed_at)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return LeadStatusHistoryResponse(
            lead_id=lead_id,
            company_name=current.company_name,
            current_status=LeadLifecycleStatus(current.current_status),
            history=[
                LeadStatusHistoryEntry(
                    status=LeadLifecycleStatus(r.status),
                    changed_at=r.changed_at,
                    changed_by=r.changed_by,
                    notes=r.notes,
                )
                for r in rows
            ],
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_current(self, lead_id: str) -> LeadLifecycleRecord | None:
        async with AsyncSessionLocal() as session:
            return await session.get(LeadLifecycleRecord, lead_id)

    async def _upsert(
        self,
        lead_id: str,
        company_name: str,
        pipeline_run_id: str,
        status: LeadLifecycleStatus,
        changed_by: str | None,
        notes: str | None,
    ) -> None:
        now = _now()
        async with AsyncSessionLocal() as session:
            # Upsert current status
            existing = await session.get(LeadLifecycleRecord, lead_id)
            if existing:
                existing.current_status = status.value
                existing.status_updated_at = now
                existing.updated_by = changed_by
                existing.notes = notes
                session.add(existing)
            else:
                session.add(LeadLifecycleRecord(
                    lead_id=lead_id,
                    company_name=company_name,
                    pipeline_run_id=pipeline_run_id,
                    current_status=status.value,
                    status_updated_at=now,
                    updated_by=changed_by,
                    notes=notes,
                ))

            # Append history entry
            session.add(LeadLifecycleHistoryRecord(
                lead_id=lead_id,
                status=status.value,
                changed_at=now,
                changed_by=changed_by,
                notes=notes,
            ))

            await session.commit()
