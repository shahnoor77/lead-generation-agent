"""
Operational Visibility Service — Chunk 3

Orchestrates data from OpsRepository into clean response schemas.
No mutations. No business logic beyond assembly.
"""

from __future__ import annotations
import json
from fastapi import HTTPException

from app.storage.ops_repository import OpsRepository
from app.schemas.operations import (
    PipelineRunSummary,
    PipelineRunsResponse,
    RunStatusSummary,
    LeadSummary,
    RunLeadsResponse,
    LeadDetailResponse,
    LeadCompanyInfo,
    LeadIntelligence,
    GeneratedDraftView,
    FinalDraftView,
)
from app.schemas.lifecycle import LeadStatusHistoryEntry, LeadLifecycleStatus
from app.schemas.finalization import ReceiverDetails, SenderDetails

_repo = OpsRepository()


class OperationsService:

    # ── All pipeline runs ─────────────────────────────────────────────────────

    async def get_all_runs(self) -> PipelineRunsResponse:
        runs = await _repo.get_all_runs()
        summaries = []
        for run in runs:
            counts = await _repo.get_status_counts_for_run(run.id)
            summaries.append(PipelineRunSummary(
                run_id=run.id,
                industries=run.industries,
                domain=run.domain,
                location=run.location,
                country=run.country,
                started_at=run.started_at,
                completed_at=run.completed_at,
                total_discovered=run.total_discovered,
                total_enriched=run.total_enriched,
                total_evaluated=run.total_evaluated,
                total_outreach_drafts=run.total_outreach_drafts,
                status_summary=RunStatusSummary(
                    total_discovered=counts.get("DISCOVERED", 0),
                    total_enriched=counts.get("ENRICHED", 0),
                    total_qualified=counts.get("QUALIFIED", 0),
                    total_outreach_drafted=counts.get("OUTREACH_DRAFTED", 0),
                    total_ready_for_review=counts.get("READY_FOR_REVIEW", 0),
                    total_ready_to_send=counts.get("READY_TO_SEND", 0),
                    total_contacted=counts.get("CONTACTED", 0),
                    total_replied=counts.get("REPLIED", 0),
                    total_meetings=counts.get("MEETING_SCHEDULED", 0),
                    total_won=counts.get("WON", 0),
                    total_lost=counts.get("LOST", 0),
                ),
            ))
        return PipelineRunsResponse(runs=summaries, total=len(summaries))

    # ── Leads for a run ───────────────────────────────────────────────────────

    async def get_run_leads(self, run_id: str) -> RunLeadsResponse:
        run = await _repo.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Run exists but pipeline may still be processing — return empty list, not 404
        rows = await _repo.get_leads_for_run(run_id)
        leads = [
            LeadSummary(
                lead_id=r["lead_id"],
                company_name=r["company_name"],
                website=r["website"],
                location=r["location"],
                fit_score=r["fit_score"],
                decision=r["decision"],
                current_status=r["current_status"],
                approval_status=r["approval_status"],
                discovered_at=r["discovered_at"],
            )
            for r in rows
        ]
        return RunLeadsResponse(
            run_id=run_id,
            pipeline_complete=run.completed_at is not None,
            leads=leads,
            total=len(leads),
        )

    # ── Single lead detail ────────────────────────────────────────────────────

    async def get_lead_detail(self, lead_id: str) -> LeadDetailResponse:
        data = await _repo.get_lead_detail(lead_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

        ev = data["evaluated"]
        raw = data["raw"]
        enriched = data["enriched"]
        lifecycle = data["lifecycle"]
        finalized = data["finalized"]
        draft = data["draft"]
        history_rows = data["history"]

        # ── Company ───────────────────────────────────────────────────────────
        company = LeadCompanyInfo(
            company_name=ev.company_name,
            website=ev.website,
            location=ev.location,
            address=raw.address if raw else None,
            phone=raw.phone if raw else None,
            category=raw.category if raw else None,
            rating=raw.rating if raw else None,
            review_count=raw.review_count if raw else None,
        )

        # ── Intelligence ──────────────────────────────────────────────────────
        pain_points: list[str] = []
        if draft and draft.inferred_pain_points:
            try:
                pain_points = json.loads(draft.inferred_pain_points)
            except (json.JSONDecodeError, TypeError):
                pass

        intelligence = LeadIntelligence(
            enrichment_summary=enriched.summary if enriched else None,
            inferred_pain_points=pain_points,
            icp_reasoning=ev.llm_reasoning,
            rule_score=ev.rule_score,
            llm_score=ev.llm_score,
            fit_score=ev.fit_score,
            decision=ev.decision,
        )

        # ── Generated draft ───────────────────────────────────────────────────
        generated_draft = None
        if draft:
            generated_draft = GeneratedDraftView(
                subject=draft.email_subject,
                body=draft.email_body,
                language=draft.language,
                word_count=draft.word_count,
                generated_at=draft.generated_at,
            )

        # ── Final draft ───────────────────────────────────────────────────────
        final_draft = None
        if finalized:
            final_draft = FinalDraftView(
                subject=finalized.final_subject,
                body=finalized.final_body,
                finalized_at=finalized.finalized_at,
                finalized_by=finalized.finalized_by,
                approval_status=finalized.approval_status,
                approved_by=finalized.approved_by,
                approved_at=finalized.approved_at,
                receiver=ReceiverDetails(
                    receiver_name=finalized.receiver_name,
                    receiver_role=finalized.receiver_role,
                    receiver_email=finalized.receiver_email,
                    linkedin_url=finalized.receiver_linkedin_url,
                    preferred_contact_method=finalized.preferred_contact_method,
                ),
                sender=SenderDetails(
                    sender_name=finalized.sender_name,
                    sender_role=finalized.sender_role,
                    sender_company=finalized.sender_company,
                    sender_email=finalized.sender_email,
                    sender_phone=finalized.sender_phone,
                    signature=finalized.signature,
                ),
            )

        # ── Status history ────────────────────────────────────────────────────
        history = [
            LeadStatusHistoryEntry(
                status=LeadLifecycleStatus(h.status),
                changed_at=h.changed_at,
                changed_by=h.changed_by,
                notes=h.notes,
            )
            for h in history_rows
        ]

        return LeadDetailResponse(
            lead_id=lead_id,
            pipeline_run_id=ev.pipeline_run_id,
            company=company,
            intelligence=intelligence,
            generated_draft=generated_draft,
            final_draft=final_draft,
            current_status=lifecycle.current_status if lifecycle else None,
            status_history=history,
        )
