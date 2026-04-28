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
