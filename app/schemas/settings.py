"""
User Settings Schemas — Lead Discovery, ICP, Sender, Outreach, AI Agent.
All fields optional on update — only provided fields are changed.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class ICPScoringWeights(BaseModel):
    industry_match: int = Field(default=30, ge=0, le=100)
    revenue_fit: int = Field(default=20, ge=0, le=100)
    location: int = Field(default=20, ge=0, le=100)
    digital_presence: int = Field(default=15, ge=0, le=100)
    firmographic_quality: int = Field(default=15, ge=0, le=100)


class LeadDiscoverySettings(BaseModel):
    """
    Configuration for lead generation runs.
    Stored per-user and used as defaults when starting a run from Settings.
    """
    industries: list[str] = Field(
        default=["manufacturing", "logistics", "construction", "retail", "healthcare"],
        description="Target industries to search",
    )
    location: str = Field(default="Saudi Arabia", description="Primary search location")
    country: Optional[str] = Field(default=None, description="Country filter")
    area: Optional[str] = Field(default=None, description="Sub-area or city")
    domain: Optional[str] = Field(default=None, description="Business domain / niche")
    our_services: list[str] = Field(default_factory=list, description="Our services (used for ICP matching)")
    pain_points: list[str] = Field(default_factory=list, description="Known pain points to target")
    value_proposition: Optional[str] = Field(default=None, description="Our value proposition")
    excluded_categories: list[str] = Field(default_factory=list, description="Categories to exclude")
    language_preference: str = Field(default="EN", description="EN | AR | AUTO")
    notes: Optional[str] = Field(default=None, description="Additional context for the LLM")


class ICPSettings(BaseModel):
    decision_maker_titles: list[str] = Field(
        default=["CEO", "COO", "GM", "Owner", "Managing Director", "Operations Director"],
    )
    target_industries: list[str] = Field(
        default=["manufacturing", "logistics", "construction", "retail", "healthcare"],
    )
    ownership_types: list[str] = Field(
        default=["Private", "Family-owned", "SME", "Enterprise"],
    )
    revenue_min: Optional[int] = Field(default=None, description="Minimum annual revenue (USD)")
    revenue_max: Optional[int] = Field(default=None, description="Maximum annual revenue (USD)")
    growth_stage: Optional[str] = Field(default=None)
    primary_geography: Optional[str] = Field(default=None)
    min_fit_score: int = Field(default=45, ge=0, le=100)
    require_website: bool = Field(default=False)
    require_contact: bool = Field(default=False)
    scoring_weights: ICPScoringWeights = Field(default_factory=ICPScoringWeights)


class SenderSettings(BaseModel):
    """
    SMTP/IMAP sender credentials — stored encrypted separately in SenderEmailAccountRecord.
    This schema is used for read (no secrets returned) and write (passwords optional on update).
    """
    email_address: Optional[str] = Field(default=None, description="Sender email address")
    display_name: Optional[str] = Field(default=None, description="Display name for outbound mail")
    smtp_host: Optional[str] = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_username: Optional[str] = Field(default=None)
    smtp_password: Optional[str] = Field(default=None, description="Omit to keep existing password")
    use_tls: bool = Field(default=True)
    daily_limit: int = Field(default=50, ge=1, le=500)
    imap_host: Optional[str] = Field(default=None)
    imap_port: int = Field(default=993)
    imap_username: Optional[str] = Field(default=None)
    imap_password: Optional[str] = Field(default=None, description="Omit to keep existing password")
    imap_use_ssl: bool = Field(default=True)
    # Read-only flags (returned by GET, ignored on PUT)
    smtp_password_configured: Optional[bool] = Field(default=None)
    imap_password_configured: Optional[bool] = Field(default=None)
    configured: Optional[bool] = Field(default=None)


class OutreachSettings(BaseModel):
    sender_domain: Optional[str] = None
    daily_send_limit: int = Field(default=50, ge=1, le=500)
    send_window_start: str = Field(default="09:00", description="HH:MM UTC")
    send_window_end: str = Field(default="17:00", description="HH:MM UTC")
    language_default: str = Field(default="EN", description="EN | AR | AUTO")
    followup_enabled: bool = True
    reply_check_enabled: bool = True
    followup_max_attempts: int = Field(default=4, ge=1, le=10)
    followup_interval_hours: int = Field(default=48, ge=1, le=720)


class AIAgentSettings(BaseModel):
    model: str = Field(default="qwen2.5-coder:14b")
    agent_mode: str = Field(default="semi-autonomous", description="semi-autonomous | autonomous")
    email_tone: str = Field(default="formal-business", description="executive-direct | formal-business | problem-specific")
    hypothesis_depth: str = Field(default="concise", description="concise | standard | detailed")
    summary_depth: str = Field(default="standard", description="concise | standard | detailed")


class UserSettingsRequest(BaseModel):
    """Full settings update — all groups optional."""
    lead_discovery: Optional[LeadDiscoverySettings] = None
    icp: Optional[ICPSettings] = None
    sender: Optional[SenderSettings] = None
    outreach: Optional[OutreachSettings] = None
    ai_agent: Optional[AIAgentSettings] = None


class UserSettingsResponse(BaseModel):
    user_id: str
    lead_discovery: LeadDiscoverySettings
    icp: ICPSettings
    sender: SenderSettings
    outreach: OutreachSettings
    ai_agent: AIAgentSettings
    updated_at: Optional[str] = None
    sandbox_outreach_available: bool = True
