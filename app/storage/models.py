"""
PostgreSQL ORM models — one table per pipeline stage.
All datetime fields use naive UTC (datetime.utcnow) to match
TIMESTAMP WITHOUT TIME ZONE columns created by SQLModel.
"""

from __future__ import annotations
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


def _utcnow() -> datetime:
    return datetime.utcnow()


class PipelineRunRecord(SQLModel, table=True):
    __tablename__ = "pipeline_runs"
    id: str = Field(primary_key=True)
    location: str
    industries: str
    domain: Optional[str] = None
    country: Optional[str] = None
    area: Optional[str] = None
    language_preference: str = "AUTO"
    total_discovered: int = 0
    total_enriched: int = 0
    total_filtered_out: int = 0
    total_evaluated: int = 0
    total_rejected_by_icp: int = 0
    total_outreach_drafts: int = 0
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    errors: str = Field(default="[]")


class RawLeadRecord(SQLModel, table=True):
    __tablename__ = "raw_leads"
    lead_id: str = Field(primary_key=True)
    trace_id: str
    pipeline_run_id: str = Field(index=True)
    source: str = "google_maps"
    discovered_at: datetime = Field(default_factory=_utcnow)
    company_name: str
    location: str
    category: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    google_maps_url: Optional[str] = None
    raw_json: str = Field(default="{}")


class EnrichedLeadRecord(SQLModel, table=True):
    __tablename__ = "enriched_leads"
    lead_id: str = Field(primary_key=True)
    trace_id: str
    pipeline_run_id: str = Field(index=True)
    enriched_at: datetime = Field(default_factory=_utcnow)
    company_name: str
    location: str
    website: Optional[str] = None
    enrichment_success: bool = False
    summary: Optional[str] = None
    industry: Optional[str] = None
    business_type: str = "UNKNOWN"
    services_detected: str = Field(default="[]")
    key_people: str = Field(default="[]")
    contact_email: Optional[str] = None
    linkedin_url: Optional[str] = None
    founding_year: Optional[int] = None
    language_of_website: Optional[str] = None
    enrichment_error: Optional[str] = None
    raw_json: str = Field(default="{}")


class FilteredLeadRecord(SQLModel, table=True):
    __tablename__ = "filtered_leads"
    lead_id: str = Field(primary_key=True)
    trace_id: str
    pipeline_run_id: str = Field(index=True)
    filtered_at: datetime = Field(default_factory=_utcnow)
    company_name: str
    location: str
    category: Optional[str] = None
    website: Optional[str] = None
    enrichment_success: bool = False
    filter_reason: str
    raw_json: str = Field(default="{}")


class EvaluatedLeadRecord(SQLModel, table=True):
    __tablename__ = "evaluated_leads"
    lead_id: str = Field(primary_key=True)
    trace_id: str
    pipeline_run_id: str = Field(index=True)
    evaluated_at: datetime = Field(default_factory=_utcnow)
    company_name: str
    location: str
    website: Optional[str] = None
    fit_score: int = 0
    rule_score: int = 0
    llm_score: Optional[int] = None
    llm_was_called: bool = False
    confidence_score: float = 0.0
    decision: str = "REJECTED"
    llm_reasoning: Optional[str] = None
    disqualification_reason: Optional[str] = None
    raw_json: str = Field(default="{}")


class OutreachRecord(SQLModel, table=True):
    __tablename__ = "outreach_drafts"
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: str = Field(index=True)
    trace_id: str
    pipeline_run_id: str = Field(index=True)
    generated_at: datetime = Field(default_factory=_utcnow)
    email_subject: str
    email_body: str
    language: str
    word_count: int = 0
    inferred_pain_points: str = Field(default="[]")
    personalization_hooks: str = Field(default="[]")
    approved: bool = False
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None


# ── Lead Lifecycle Tracking (Chunk 1) ─────────────────────────────────────────

class LeadLifecycleRecord(SQLModel, table=True):
    """
    Current lifecycle status for a lead.
    One row per lead — upserted as status changes.
    """
    __tablename__ = "lead_lifecycle"

    lead_id: str = Field(primary_key=True)
    company_name: str
    pipeline_run_id: str = Field(index=True)
    current_status: str = "DISCOVERED"          # LeadLifecycleStatus value
    status_updated_at: datetime = Field(default_factory=_utcnow)
    updated_by: Optional[str] = None            # username or "pipeline"
    notes: Optional[str] = None


class LeadLifecycleHistoryRecord(SQLModel, table=True):
    """
    Append-only history of every status change for a lead.
    Never updated — only inserted.
    """
    __tablename__ = "lead_lifecycle_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: str = Field(index=True)
    status: str                                 # LeadLifecycleStatus value
    changed_at: datetime = Field(default_factory=_utcnow)
    changed_by: Optional[str] = None
    notes: Optional[str] = None


# ── Draft Finalization Layer (Chunk 2) ────────────────────────────────────────

class FinalizedDraftRecord(SQLModel, table=True):
    """
    Stores the human-edited final draft alongside the original generated draft.

    CRITICAL: generated_subject / generated_body are NEVER overwritten.
    final_subject / final_body are the editable human versions.
    Both always coexist in this table.

    approval_status: "PENDING_REVIEW" | "APPROVED"
    System never sets approval_status = "APPROVED" — only humans do.
    """
    __tablename__ = "finalized_drafts"

    lead_id: str = Field(primary_key=True)       # one finalized draft per lead
    pipeline_run_id: str = Field(index=True)
    company_name: str

    # ── Generated draft (system-owned, immutable after creation) ──────────────
    generated_subject: str
    generated_body: str
    generated_at: datetime = Field(default_factory=_utcnow)

    # ── Final draft (human-edited, always editable) ───────────────────────────
    final_subject: str
    final_body: str
    finalized_at: datetime = Field(default_factory=_utcnow)
    finalized_by: Optional[str] = None
    notes: Optional[str] = None

    # ── Receiver details (operator-filled) ────────────────────────────────────
    receiver_name: str
    receiver_role: Optional[str] = None
    receiver_email: str
    receiver_linkedin_url: Optional[str] = None
    preferred_contact_method: str = "email"

    # ── Sender details (operator-filled) ──────────────────────────────────────
    sender_name: str
    sender_role: Optional[str] = None
    sender_company: Optional[str] = None
    sender_email: str
    sender_phone: Optional[str] = None
    signature: Optional[str] = None

    # ── Approval (manual only — system never auto-approves) ───────────────────
    approval_status: str = "PENDING_REVIEW"      # "PENDING_REVIEW" | "APPROVED"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
