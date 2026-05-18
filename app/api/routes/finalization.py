"""
Draft Finalization endpoints — Chunk 2

PATCH /api/v1/leads/{lead_id}/finalize-draft   Finalize (or re-finalize) a draft
GET   /api/v1/leads/{lead_id}/finalize-draft   Get the current finalized draft
"""

from fastapi import APIRouter, Depends
from app.schemas.finalization import FinalizeDraftRequest, FinalizeDraftResponse
from app.services.finalization import DraftFinalizationService
from app.api.dependencies import get_current_user
from app.storage.models import UserRecord

router = APIRouter()
_svc = DraftFinalizationService()


@router.patch("/leads/{lead_id}/finalize-draft", response_model=FinalizeDraftResponse)
async def finalize_draft(
    lead_id: str,
    body: FinalizeDraftRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> FinalizeDraftResponse:
    """
    Finalize a lead's outreach draft.

    - Preserves the original AI-generated draft (never overwritten).
    - Saves the human-edited final draft (always editable — call again to update).
    - Saves receiver and sender details.
    - Sets approval_status = PENDING_REVIEW (never auto-approved).
    - Moves lifecycle status → READY_FOR_REVIEW.
    """
    return await _svc.finalize(lead_id=lead_id, payload=body, user_id=current_user.id)


@router.get("/leads/{lead_id}/finalize-draft", response_model=FinalizeDraftResponse)
async def get_finalized_draft(
    lead_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> FinalizeDraftResponse:
    """Retrieve the current finalized draft for a lead."""
    return await _svc.get_finalized_draft(lead_id)
