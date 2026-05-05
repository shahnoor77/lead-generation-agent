"""
Operational Visibility Repository — Chunk 3

All read queries for the operator visibility layer.
No mutations. No business logic. Pure data access.
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Optional

from sqlmodel import select
from app.storage.database import AsyncSessionLocal
from app.storage.models import (
    PipelineRunRecord,
    RawLeadRecord,
    EvaluatedLeadRecord,
    OutreachRecord,
    LeadLifecycleRecord,
    LeadLifecycleHistoryRecord,
    FinalizedDraftRecord,
    EnrichedLeadRecord,
)


class OpsRepository:

    # ── Pipeline Runs ─────────────────────────────────────────────────────────

    async def get_all_runs(self) -> list[PipelineRunRecord]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PipelineRunRecord).order_by(PipelineRunRecord.started_at.desc())
            )
            return list(result.scalars().all())

    async def get_run(self, run_id: str) -> Optional[PipelineRunRecord]:
        async with AsyncSessionLocal() as session:
            return await session.get(PipelineRunRecord, run_id)

    # ── Leads for a run ───────────────────────────────────────────────────────

    async def get_leads_for_run(self, run_id: str) -> list[dict]:
        """
        Returns evaluated leads joined with lifecycle status and approval status.
        One query per table — no ORM joins to keep it simple and fast.
        """
        async with AsyncSessionLocal() as session:
            # Evaluated leads for this run
            eval_result = await session.execute(
                select(EvaluatedLeadRecord)
                .where(EvaluatedLeadRecord.pipeline_run_id == run_id)
                .order_by(EvaluatedLeadRecord.fit_score.desc())
            )
            evaluated = list(eval_result.scalars().all())

            if not evaluated:
                return []

            lead_ids = [e.lead_id for e in evaluated]

            # Lifecycle status for these leads
            lc_result = await session.execute(
                select(LeadLifecycleRecord)
                .where(LeadLifecycleRecord.lead_id.in_(lead_ids))
            )
            lifecycle_map = {r.lead_id: r for r in lc_result.scalars().all()}

            # Finalized draft approval status
            fd_result = await session.execute(
                select(FinalizedDraftRecord)
                .where(FinalizedDraftRecord.lead_id.in_(lead_ids))
            )
            finalized_map = {r.lead_id: r for r in fd_result.scalars().all()}

            # Raw lead for discovered_at + extra fields
            raw_result = await session.execute(
                select(RawLeadRecord)
                .where(RawLeadRecord.lead_id.in_(lead_ids))
            )
            raw_map = {r.lead_id: r for r in raw_result.scalars().all()}

        rows = []
        for ev in evaluated:
            lc = lifecycle_map.get(ev.lead_id)
            fd = finalized_map.get(ev.lead_id)
            raw = raw_map.get(ev.lead_id)
            rows.append({
                "lead_id": ev.lead_id,
                "company_name": ev.company_name,
                "website": ev.website,
                "location": ev.location,
                "fit_score": ev.fit_score,
                "decision": ev.decision,
                "current_status": lc.current_status if lc else None,
                "approval_status": fd.approval_status if fd else None,
                "discovered_at": raw.discovered_at if raw else ev.evaluated_at,
            })
        return rows

    # ── Lifecycle status counts for a run ─────────────────────────────────────

    async def get_status_counts_for_run(self, run_id: str) -> dict[str, int]:
        """Count leads per lifecycle status for a given run."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(LeadLifecycleRecord)
                .where(LeadLifecycleRecord.pipeline_run_id == run_id)
            )
            rows = result.scalars().all()

        counts: dict[str, int] = {}
        for row in rows:
            counts[row.current_status] = counts.get(row.current_status, 0) + 1
        return counts

    # ── Single lead detail ────────────────────────────────────────────────────

    async def get_lead_detail(self, lead_id: str) -> Optional[dict]:
        """
        Fetches all data for a single lead across all tables.
        Returns None if the lead doesn't exist in evaluated_leads.
        """
        async with AsyncSessionLocal() as session:
            evaluated = await session.get(EvaluatedLeadRecord, lead_id)
            if evaluated is None:
                return None

            raw = await session.get(RawLeadRecord, lead_id)
            enriched = await session.get(EnrichedLeadRecord, lead_id)
            lifecycle = await session.get(LeadLifecycleRecord, lead_id)
            finalized = await session.get(FinalizedDraftRecord, lead_id)

            # Latest generated draft
            draft_result = await session.execute(
                select(OutreachRecord)
                .where(OutreachRecord.lead_id == lead_id)
                .order_by(OutreachRecord.generated_at.desc())
                .limit(1)
            )
            draft = draft_result.scalar_one_or_none()

            # Full status history
            history_result = await session.execute(
                select(LeadLifecycleHistoryRecord)
                .where(LeadLifecycleHistoryRecord.lead_id == lead_id)
                .order_by(LeadLifecycleHistoryRecord.changed_at)
            )
            history = list(history_result.scalars().all())

        return {
            "evaluated": evaluated,
            "raw": raw,
            "enriched": enriched,
            "lifecycle": lifecycle,
            "finalized": finalized,
            "draft": draft,
            "history": history,
        }

    # ── Raw leads for a run (Discovered Leads page) ───────────────────────────

    async def get_raw_leads_for_run(self, run_id: str) -> list[RawLeadRecord]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RawLeadRecord)
                .where(RawLeadRecord.pipeline_run_id == run_id)
                .order_by(RawLeadRecord.discovered_at)
            )
            return list(result.scalars().all())

    async def get_enriched_for_run(self, run_id: str) -> list[EnrichedLeadRecord]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EnrichedLeadRecord)
                .where(EnrichedLeadRecord.pipeline_run_id == run_id)
                .order_by(EnrichedLeadRecord.enriched_at)
            )
            return list(result.scalars().all())

    # ── Cross-run deduplication ───────────────────────────────────────────────

    async def get_known_company_keys(self, location: str) -> set[str]:
        """
        Returns a set of 'company_name|location' keys already in the DB.
        Used to skip companies already discovered in previous runs.
        Normalised to lowercase for case-insensitive matching.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RawLeadRecord.company_name, RawLeadRecord.location)
                .where(RawLeadRecord.location.ilike(f"%{location}%"))
            )
            rows = result.all()
        return {f"{r[0].lower()}|{r[1].lower()}" for r in rows}
