"""
Operational Visibility endpoints — Chunk 3

GET /api/v1/runs                        All pipeline runs with status summaries
GET /api/v1/runs/{run_id}/leads         All leads for a run (Kanban view)
GET /api/v1/leads/{lead_id}             Full lead detail (operator working screen)
"""

from fastapi import APIRouter
from app.schemas.operations import (
    PipelineRunsResponse,
    RunLeadsResponse,
    LeadDetailResponse,
)
from app.services.operations import OperationsService

router = APIRouter()
_svc = OperationsService()


@router.get("/runs", response_model=PipelineRunsResponse)
async def get_all_runs() -> PipelineRunsResponse:
    """
    List all pipeline runs, newest first.
    Each run includes a status summary showing how many leads
    are at each lifecycle stage.
    """
    return await _svc.get_all_runs()


@router.get("/runs/{run_id}/leads", response_model=RunLeadsResponse)
async def get_run_leads(run_id: str) -> RunLeadsResponse:
    """
    Get all evaluated leads for a pipeline run.
    Returns lead summaries sorted by fit_score descending.
    Includes current lifecycle status and approval status per lead.
    Returns 404 if run_id does not exist.
    """
    return await _svc.get_run_leads(run_id)


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_lead_detail(lead_id: str) -> LeadDetailResponse:
    """
    Full operator view for a single lead.

    Returns:
    - Company info (name, website, location, phone, address, category)
    - Intelligence (enrichment summary, pain points, ICP scores, reasoning)
    - Generated draft (AI-produced, read-only)
    - Final draft (human-edited, with receiver/sender details)
    - Current lifecycle status
    - Full status history with timestamps and notes

    Returns 404 if lead_id does not exist.
    """
    return await _svc.get_lead_detail(lead_id)
