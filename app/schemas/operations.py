"""
Operational Visibility Layer — Chunk 3

Response schemas for operator-facing read APIs.
These are read-only views — no mutations happen here.
"""

from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel

from app.schemas.lifecycle import LeadLifecycleStatus, LeadStatusHistoryEntry
from app.schemas.finalization import ReceiverDetails, SenderDetails


# ── Pipeline Runs ─────────────────────────────────────────────────────────────

class RunStatusSummary(BaseModel):
    """Lifecycle counts across all leads in a run."""
    total_discovered: int = 0
    total_enriched: int = 0
    total_qualified: int = 0
    total_outreach_drafted: int = 0
    total_ready_for_review: int = 0
    total_ready_to_send: int = 0
    total_contacted: int = 0
    total_replied: int = 0
    total_meetings: int = 0
    total_won: int = 0
    total_lost: int = 0


class PipelineRunSummary(BaseModel):
    """One row in the runs list."""
    run_id: str
    industries: str
    domain: Optional[str]
    location: str
    country: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    total_discovered: int
    total_enriched: int
    total_evaluated: int
    total_outreach_drafts: int
    status_summary: RunStatusSummary


class PipelineRunsResponse(BaseModel):
    runs: list[PipelineRunSummary]
    total: int


# ── Leads for a Run ───────────────────────────────────────────────────────────

class LeadSummary(BaseModel):
    """One row in the leads-for-run list (Kanban card)."""
    lead_id: str
    company_name: str
    website: Optional[str]
    location: str
    fit_score: int
    decision: str                       # QUALIFIED | REJECTED
    current_status: Optional[str]       # LeadLifecycleStatus value
    approval_status: Optional[str]      # PENDING_REVIEW | APPROVED | None
    discovered_at: datetime


class RunLeadsResponse(BaseModel):
    run_id: str
    pipeline_complete: bool          # False while pipeline is still running
    leads: list[LeadSummary]
    total: int


# ── Single Lead Detail ────────────────────────────────────────────────────────

class LeadCompanyInfo(BaseModel):
    company_name: str
    website: Optional[str]
    location: str
    address: Optional[str]
    phone: Optional[str]
    category: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]


class LeadIntelligence(BaseModel):
    enrichment_summary: Optional[str]
    inferred_pain_points: list[str]
    icp_reasoning: Optional[str]
    rule_score: int
    llm_score: Optional[int]
    fit_score: int
    decision: str


class GeneratedDraftView(BaseModel):
    subject: str
    body: str
    language: str
    word_count: int
    generated_at: datetime


class FinalDraftView(BaseModel):
    subject: str
    body: str
    finalized_at: datetime
    finalized_by: Optional[str]
    approval_status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    receiver: ReceiverDetails
    sender: SenderDetails


class LeadDetailResponse(BaseModel):
    lead_id: str
    pipeline_run_id: str

    # Company
    company: LeadCompanyInfo

    # Intelligence
    intelligence: LeadIntelligence

    # Drafts
    generated_draft: Optional[GeneratedDraftView]
    final_draft: Optional[FinalDraftView]

    # Operations
    current_status: Optional[str]
    status_history: list[LeadStatusHistoryEntry]
