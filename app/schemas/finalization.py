"""
Draft Finalization Layer — Chunk 2

Separates the AI-generated draft (system-owned, immutable)
from the human-edited final draft (operator-owned, editable).

Both are always preserved. The generated draft is never overwritten.
"""

from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# ── Sub-models ────────────────────────────────────────────────────────────────

class ReceiverDetails(BaseModel):
    """Manually filled by operator. Never auto-discovered."""
    receiver_name: str = Field(..., min_length=1, max_length=200)
    receiver_role: Optional[str] = Field(default=None, max_length=200)
    receiver_email: EmailStr
    linkedin_url: Optional[str] = Field(default=None, max_length=500)
    preferred_contact_method: Optional[str] = Field(
        default="email",
        description="email | linkedin | phone",
        max_length=50,
    )


class SenderDetails(BaseModel):
    """Operator-controlled. Never inferred automatically."""
    sender_name: str = Field(..., min_length=1, max_length=200)
    sender_role: Optional[str] = Field(default=None, max_length=200)
    sender_company: Optional[str] = Field(default=None, max_length=200)
    sender_email: EmailStr
    sender_phone: Optional[str] = Field(default=None, max_length=50)
    signature: Optional[str] = Field(default=None, max_length=1000)


# ── Request ───────────────────────────────────────────────────────────────────

class FinalizeDraftRequest(BaseModel):
    """
    Payload for PATCH /api/v1/leads/{lead_id}/finalize-draft.

    final_subject and final_body are the human-edited versions.
    The original generated draft is preserved separately and never touched.
    Both receiver_details and sender_details are required to finalize.
    """
    final_subject: str = Field(..., min_length=1, max_length=200)
    final_body: str = Field(..., min_length=1, max_length=5000)
    receiver_details: ReceiverDetails
    sender_details: SenderDetails
    finalized_by: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=1000)


# ── Response ──────────────────────────────────────────────────────────────────

class FinalizeDraftResponse(BaseModel):
    lead_id: str
    company_name: str

    # Generated draft (system-owned, read-only)
    generated_subject: str
    generated_body: str
    generated_at: datetime

    # Final draft (human-edited, always editable)
    final_subject: str
    final_body: str
    finalized_at: datetime
    finalized_by: Optional[str]

    # Receiver + sender
    receiver_details: ReceiverDetails
    sender_details: SenderDetails

    # Approval — always False until explicitly approved
    approval_status: str          # "PENDING_REVIEW" | "APPROVED"
    approved_by: Optional[str]
    approved_at: Optional[datetime]

    # Lifecycle status after finalization
    lifecycle_status: str         # "READY_FOR_REVIEW"
