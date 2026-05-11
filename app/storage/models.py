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
    user_id: Optional[int] = Field(default=None, index=True)   # owner
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


# ── Auth + User Management ────────────────────────────────────────────────────

class UserRecord(SQLModel, table=True):
    """Operator accounts. Passwords stored as bcrypt hashes."""
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)


class UserLeadConfigRecord(SQLModel, table=True):
    """
    Persisted lead generation configuration per user.
    Saved automatically when a run is started.
    Restored when the user opens the New Run form.
    """
    __tablename__ = "user_lead_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    industries: str = Field(default="[]")           # JSON array
    location: str = ""
    country: Optional[str] = None
    domain: Optional[str] = None
    area: Optional[str] = None
    excluded_categories: str = Field(default="[]")
    our_services: str = Field(default="[]")
    target_pain_patterns: str = Field(default="[]")
    pain_points: str = Field(default="[]")
    value_proposition: Optional[str] = None
    language_preference: str = "EN"
    notes: Optional[str] = None
    continuous: bool = False
    continuous_interval_minutes: int = 60
    updated_at: datetime = Field(default_factory=_utcnow)


# ── User Settings (ICP + Outreach + AI Agent) ─────────────────────────────────

class UserSettingsRecord(SQLModel, table=True):
    """
    Persistent per-user configuration for ICP rules, outreach, and AI agent.
    One row per user — upserted on every save.
    """
    __tablename__ = "user_settings"

    user_id: int = Field(primary_key=True)
    updated_at: datetime = Field(default_factory=_utcnow)

    # ── ICP Settings ──────────────────────────────────────────────────────────
    icp_decision_maker_titles: str = Field(
        default='["CEO", "COO", "GM", "Owner", "Managing Director", "Operations Director"]'
    )                                           # JSON array
    icp_target_industries: str = Field(
        default='["manufacturing", "logistics", "construction", "retail", "healthcare"]'
    )                                           # JSON array
    icp_ownership_types: str = Field(
        default='["Private", "Family-owned", "SME", "Enterprise"]'
    )                                           # JSON array
    icp_revenue_min: Optional[int] = None       # USD
    icp_revenue_max: Optional[int] = None       # USD
    icp_growth_stage: Optional[str] = None      # e.g. "Scaling up to $200M"
    icp_primary_geography: Optional[str] = None # e.g. "Saudi Arabia, UAE, Pakistan"
    icp_min_fit_score: int = 45                 # leads below this are REJECTED
    icp_require_website: bool = False           # if True, filter leads without website
    icp_require_contact: bool = False           # if True, filter leads without email/phone

    # ── Outreach Settings (stub — Outreach Agent built later) ─────────────────
    outreach_sender_domain: Optional[str] = None
    outreach_daily_send_limit: int = 50
    outreach_send_window_start: str = "09:00"   # HH:MM UTC
    outreach_send_window_end: str = "17:00"
    outreach_language_default: str = "EN"
    outreach_followup_enabled: bool = True
    outreach_reply_check_enabled: bool = True
    outreach_followup_max_attempts: int = 4
    outreach_followup_interval_hours: int = 48

    # ── AI Agent Settings ─────────────────────────────────────────────────────
    ai_model: str = "qwen2.5-coder:14b"
    ai_agent_mode: str = "semi-autonomous"      # semi-autonomous | manual
    ai_email_tone: str = "formal-business"      # executive-direct | formal-business | problem-specific
    ai_hypothesis_depth: str = "concise"        # concise (2-3 sentences) | standard | detailed
    ai_summary_depth: str = "standard"          # concise | standard | detailed


# ── Outreach Agent ────────────────────────────────────────────────────────────

class SenderEmailAccountRecord(SQLModel, table=True):
    """
    SMTP credentials for a sender email account.
    One user can have multiple sender accounts (different domains).
    Passwords stored encrypted — never in plaintext.
    """
    __tablename__ = "sender_email_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    email_address: str = Field(index=True)
    display_name: str = ""                      # "Ali Hassan — XYZ Consulting"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password_encrypted: str = ""           # encrypted with SECRET_KEY
    use_tls: bool = True
    imap_host: Optional[str] = None
    imap_port: int = 993
    imap_username: Optional[str] = None
    imap_password_encrypted: Optional[str] = None
    imap_use_ssl: bool = True
    is_active: bool = True
    daily_limit: int = 50
    created_at: datetime = Field(default_factory=_utcnow)


class OutreachSentRecord(SQLModel, table=True):
    """
    Append-only log of every email sent.
    Prevents duplicate sends — checked before every send attempt.
    """
    __tablename__ = "outreach_sent"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    lead_id: str = Field(index=True)
    finalized_draft_id: str                     # lead_id of FinalizedDraftRecord
    sender_email: str
    receiver_email: str
    subject: str
    sent_at: datetime = Field(default_factory=_utcnow)
    status: str = "sent"                        # sent | failed | bounced
    campaign_stage: str = "initial"             # initial | followup | reply
    error_message: Optional[str] = None


class OutreachReplyRecord(SQLModel, table=True):
    """
    Inbound reply log for follow-up automation and deduplication.
    """
    __tablename__ = "outreach_replies"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    lead_id: str = Field(index=True)
    receiver_email: str
    message_id: str = Field(index=True)
    reply_subject: str
    reply_body: str
    intent: str = "neutral"                     # positive | neutral | negative
    received_at: datetime = Field(default_factory=_utcnow)


class OutreachJobRecord(SQLModel, table=True):
    """
    Tracks active outreach jobs per user.
    A job runs continuously until stopped or config changes.
    """
    __tablename__ = "outreach_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)  # one active job per user
    is_active: bool = True
    sender_account_id: int
    industry_filter: Optional[str] = None      # JSON array — filter by industry
    location_filter: Optional[str] = None      # filter by location
    daily_sent_today: int = 0
    last_sent_date: Optional[str] = None        # YYYY-MM-DD
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
