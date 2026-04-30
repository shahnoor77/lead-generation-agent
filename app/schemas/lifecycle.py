"""
Lead Lifecycle State Tracking — Chunk 1

Separate from the pipeline-internal LeadStatus enum.
This tracks the human-facing CRM-style lifecycle of a lead
from first discovery through to won/lost.

Automatic transitions (set by pipeline):
  DISCOVERED → ENRICHED → QUALIFIED → OUTREACH_DRAFTED

Manual transitions (set by human via PATCH /api/v1/leads/{lead_id}/status):
  OUTREACH_DRAFTED → READY_FOR_REVIEW → READY_TO_SEND
  → CONTACTED → REPLIED → MEETING_SCHEDULED → WON | LOST | ARCHIVED
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class LeadLifecycleStatus(str, Enum):
    # ── Set automatically by pipeline ─────────────────────────────────────────
    DISCOVERED        = "DISCOVERED"        # raw lead found by discovery
    ENRICHED          = "ENRICHED"          # website scraped + summarized
    QUALIFIED         = "QUALIFIED"         # ICP score >= threshold
    OUTREACH_DRAFTED  = "OUTREACH_DRAFTED"  # email draft generated

    # ── Set manually by human ─────────────────────────────────────────────────
    READY_FOR_REVIEW  = "READY_FOR_REVIEW"  # draft reviewed, ready to check
    READY_TO_SEND     = "READY_TO_SEND"     # approved, ready to send
    CONTACTED         = "CONTACTED"         # outreach sent
    REPLIED           = "REPLIED"           # prospect replied
    MEETING_SCHEDULED = "MEETING_SCHEDULED" # meeting booked
    WON               = "WON"               # deal / meeting confirmed
    LOST              = "LOST"              # no longer pursuing
    ARCHIVED          = "ARCHIVED"          # removed from active pipeline


# Statuses the pipeline sets automatically — humans cannot set these via API
_PIPELINE_STATUSES = {
    LeadLifecycleStatus.DISCOVERED,
    LeadLifecycleStatus.ENRICHED,
    LeadLifecycleStatus.QUALIFIED,
    LeadLifecycleStatus.OUTREACH_DRAFTED,
}

# Valid forward transitions — prevents nonsensical jumps
# Key: current status → set of allowed next statuses
ALLOWED_TRANSITIONS: dict[LeadLifecycleStatus, set[LeadLifecycleStatus]] = {
    LeadLifecycleStatus.DISCOVERED:        {LeadLifecycleStatus.ENRICHED, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.ENRICHED:          {LeadLifecycleStatus.QUALIFIED, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.QUALIFIED:         {LeadLifecycleStatus.OUTREACH_DRAFTED, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.OUTREACH_DRAFTED:  {LeadLifecycleStatus.READY_FOR_REVIEW, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.READY_FOR_REVIEW:  {LeadLifecycleStatus.READY_TO_SEND, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.READY_TO_SEND:     {LeadLifecycleStatus.CONTACTED, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.CONTACTED:         {LeadLifecycleStatus.REPLIED, LeadLifecycleStatus.LOST, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.REPLIED:           {LeadLifecycleStatus.MEETING_SCHEDULED, LeadLifecycleStatus.LOST, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.MEETING_SCHEDULED: {LeadLifecycleStatus.WON, LeadLifecycleStatus.LOST, LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.WON:               {LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.LOST:              {LeadLifecycleStatus.ARCHIVED},
    LeadLifecycleStatus.ARCHIVED:          set(),  # terminal
}


def is_pipeline_status(status: LeadLifecycleStatus) -> bool:
    return status in _PIPELINE_STATUSES


def is_valid_transition(current: LeadLifecycleStatus, next_status: LeadLifecycleStatus) -> bool:
    return next_status in ALLOWED_TRANSITIONS.get(current, set())


# ── API request/response models ───────────────────────────────────────────────

class UpdateLeadStatusRequest(BaseModel):
    status: LeadLifecycleStatus
    notes: Optional[str] = Field(default=None, max_length=1000)
    updated_by: Optional[str] = Field(default=None, max_length=100)


class LeadStatusResponse(BaseModel):
    lead_id: str
    company_name: str
    current_status: LeadLifecycleStatus
    status_updated_at: datetime
    updated_by: Optional[str]
    notes: Optional[str]


class LeadStatusHistoryEntry(BaseModel):
    status: LeadLifecycleStatus
    changed_at: datetime
    changed_by: Optional[str]
    notes: Optional[str]


class LeadStatusHistoryResponse(BaseModel):
    lead_id: str
    company_name: str
    current_status: LeadLifecycleStatus
    history: list[LeadStatusHistoryEntry]
