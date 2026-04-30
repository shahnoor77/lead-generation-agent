"""
Draft Finalization endpoints — Chunk 2

PATCH /api/v1/leads/{lead_id}/finalize-draft   Finalize (or re-finalize) a draft
GET   /api/v1/leads/{lead_id}/finalize-draft   Get the current finalized draft
"""

from fastapi import APIRouter
from app.schemas.finalization import FinalizeDraftRequest, FinalizeDraftResponse
from app.services.finalization import DraftFinalizationService

router = APIRouter()
_svc = DraftFinalizationService()


@router.patch("/leads/{lead_id}/finalize-draft", response_model=FinalizeDraftResponse)
async def finalize_draft(
    lead_id: str,
    body: FinalizeDraftRequest,
) -> FinalizeDraftResponse:
    """
    Finalize a lead's outreach draft.

    - Preserves the original AI-generated draft (never overwritten).
    - Saves the human-edited final draft (always editable — call again to update).
    - Saves receiver and sender details.
    - Sets approval_status = PENDING_REVIEW (never auto-approved).
    - Moves lifecycle status → READY_FOR_REVIEW.

    Example:
    PATCH /api/v1/leads/abc-123/finalize-draft
    {
      "final_subject": "Reducing operational bottlenecks at ABC Manufacturing",
      "final_body": "Dear Mr. Ahmed, ...",
      "receiver_details": {
        "receiver_name": "Ahmed Khan",
        "receiver_role": "Operations Director",
        "receiver_email": "ahmed@abc.com",
        "preferred_contact_method": "email"
      },
      "sender_details": {
        "sender_name": "Ali Hassan",
        "sender_role": "Business Consultant",
        "sender_company": "XYZ Consulting",
        "sender_email": "ali@xyz.com",
        "sender_phone": "+966500000000",
        "signature": "Best regards,\\nAli Hassan"
      },
      "finalized_by": "ali.hassan"
    }
    """
    return await _svc.finalize(lead_id=lead_id, payload=body)


@router.get("/leads/{lead_id}/finalize-draft", response_model=FinalizeDraftResponse)
async def get_finalized_draft(lead_id: str) -> FinalizeDraftResponse:
    """Retrieve the current finalized draft for a lead."""
    return await _svc.get_finalized_draft(lead_id)
