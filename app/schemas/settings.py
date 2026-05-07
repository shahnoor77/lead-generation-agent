"""
User Settings Schemas — ICP, Outreach, AI Agent.
All fields optional on update — only provided fields are changed.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class ICPSettings(BaseModel):
    decision_maker_titles: list[str] = Field(
        default=["CEO", "COO", "GM", "Owner", "Managing Director", "Operations Director"],
        description="Job titles of decision makers to target",
    )
    target_industries: list[str] = Field(
        default=["manufacturing", "logistics", "construction", "retail", "healthcare"],
    )
    ownership_types: list[str] = Field(
        default=["Private", "Family-owned", "SME", "Enterprise"],
        description="Company ownership types to target",
    )
    revenue_min: Optional[int] = Field(default=None, description="Minimum annual revenue (USD)")
    revenue_max: Optional[int] = Field(default=None, description="Maximum annual revenue (USD)")
    growth_stage: Optional[str] = Field(default=None, description="e.g. 'Scaling up to $200M'")
    primary_geography: Optional[str] = Field(default=None, description="e.g. 'Saudi Arabia, UAE'")
    min_fit_score: int = Field(default=45, ge=0, le=100, description="Minimum ICP score to qualify a lead")
    require_website: bool = Field(default=False, description="Filter out leads without a website")
    require_contact: bool = Field(default=False, description="Filter out leads without email or phone")


class OutreachSettings(BaseModel):
    """Stub — Outreach Agent built later. Persisted now for future use."""
    sender_domain: Optional[str] = None
    daily_send_limit: int = Field(default=50, ge=1, le=500)
    send_window_start: str = Field(default="09:00", description="HH:MM UTC")
    send_window_end: str = Field(default="17:00", description="HH:MM UTC")
    language_default: str = Field(default="EN", description="EN | AR | AUTO")


class AIAgentSettings(BaseModel):
    model: str = Field(default="qwen2.5-coder:14b", description="Ollama model name")
    agent_mode: str = Field(
        default="semi-autonomous",
        description="semi-autonomous | manual",
    )
    email_tone: str = Field(
        default="formal-business",
        description="executive-direct | formal-business | problem-specific",
    )
    hypothesis_depth: str = Field(
        default="concise",
        description="concise (2-3 sentences) | standard | detailed",
    )
    summary_depth: str = Field(
        default="standard",
        description="concise | standard | detailed",
    )


class UserSettingsRequest(BaseModel):
    """Full settings update — all groups optional."""
    icp: Optional[ICPSettings] = None
    outreach: Optional[OutreachSettings] = None
    ai_agent: Optional[AIAgentSettings] = None


class UserSettingsResponse(BaseModel):
    user_id: int
    icp: ICPSettings
    outreach: OutreachSettings
    ai_agent: AIAgentSettings
    updated_at: Optional[str] = None
