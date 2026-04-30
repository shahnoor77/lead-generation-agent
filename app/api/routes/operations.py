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
from app.storage.database import AsyncSessionLocal

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


@router.get("/runs/{run_id}/discovered")
async def get_run_discovered(run_id: str) -> dict:
    """
    All raw + enriched leads discovered in a run.
    Returns: company name, website, phone, email, LinkedIn, address, category, industry.
    """
    from app.storage.ops_repository import OpsRepository
    from app.storage.models import EvaluatedLeadRecord
    from sqlmodel import select

    repo = OpsRepository()
    run = await repo.get_run(run_id)
    if run is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    raw_leads = await repo.get_raw_leads_for_run(run_id)
    enriched_leads = await repo.get_enriched_for_run(run_id)
    enriched_map = {e.lead_id: e for e in enriched_leads}

    # Also get ICP decisions for qualification status
    async with AsyncSessionLocal() as session:
        eval_result = await session.execute(
            select(EvaluatedLeadRecord).where(EvaluatedLeadRecord.pipeline_run_id == run_id)
        )
        eval_map = {r.lead_id: r for r in eval_result.scalars().all()}

    leads = []
    for raw in raw_leads:
        enr = enriched_map.get(raw.lead_id)
        ev = eval_map.get(raw.lead_id)
        leads.append({
            "lead_id": raw.lead_id,
            "company_name": raw.company_name,
            "category": raw.category,
            "location": raw.location,
            "address": raw.address,
            "phone": raw.phone,
            "website": raw.website,
            "contact_email": enr.contact_email if enr else None,
            "linkedin_url": enr.linkedin_url if enr else None,
            "industry": enr.industry if enr else None,
            "business_type": enr.business_type if enr else None,
            "enrichment_success": enr.enrichment_success if enr else False,
            "icp_decision": ev.decision if ev else None,
            "fit_score": ev.fit_score if ev else None,
            "discovered_at": raw.discovered_at.isoformat() if raw.discovered_at else None,
        })

    return {"pipeline_run_id": run_id, "total": len(leads), "leads": leads}
