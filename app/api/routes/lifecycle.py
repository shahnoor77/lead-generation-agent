"""
Lead Lifecycle endpoints — Chunk 1

PATCH /api/v1/leads/{lead_id}/status   Update lead status (human)
GET   /api/v1/leads/{lead_id}/status   Get current status
GET   /api/v1/leads/{lead_id}/status/history  Full status history
"""

from fastapi import APIRouter, Depends
from app.schemas.lifecycle import (
    UpdateLeadStatusRequest,
    LeadStatusResponse,
    LeadStatusHistoryResponse,
)
from app.services.lifecycle import LeadLifecycleService
from app.api.dependencies import get_current_user
from app.storage.models import UserRecord

router = APIRouter()
_svc = LeadLifecycleService()


@router.patch("/leads/{lead_id}/status", response_model=LeadStatusResponse)
async def update_lead_status(
    lead_id: str,
    body: UpdateLeadStatusRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> LeadStatusResponse:
    """
    Update a lead's lifecycle status manually.

    Example:
    PATCH /api/v1/leads/abc-123/status
    {
      "status": "CONTACTED",
      "notes": "Sent intro email via LinkedIn",
      "updated_by": "john.doe"
    }

    Invalid transitions return 422. Pipeline-only statuses return 422.
    Lead not found returns 404.
    """
    return await _svc.update_status(
        lead_id=lead_id,
        new_status=body.status,
        notes=body.notes,
        updated_by=body.updated_by,
        user_id=current_user.id,
    )


@router.get("/leads/{lead_id}/status", response_model=LeadStatusResponse)
async def get_lead_status(
    lead_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> LeadStatusResponse:
    """Get the current lifecycle status of a lead."""
    return await _svc.get_status(lead_id)


@router.get("/leads/{lead_id}/status/history", response_model=LeadStatusHistoryResponse)
async def get_lead_status_history(
    lead_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> LeadStatusHistoryResponse:
    """Get the full status change history for a lead."""
    return await _svc.get_history(lead_id)
