"""
Lead generation endpoints.

POST /api/v1/leads/generate
    Starts the pipeline as a background task.
    Returns run_id immediately — pipeline runs async in the background.

GET /api/v1/leads/runs/{run_id}
    Poll for results of a pipeline run.

GET /api/v1/leads/runs/{run_id}/drafts
    Get outreach drafts for a completed run.
"""

import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.schemas import BusinessContext, EvaluatedLead, OutreachOutput
from app.pipeline import PipelineOrchestrator, PipelineResult
from app.storage.database import AsyncSessionLocal
from app.storage.models import PipelineRunRecord, OutreachRecord, EvaluatedLeadRecord
from app.core.logging import get_logger
from sqlmodel import select

router = APIRouter()
logger = get_logger(__name__)

# In-memory run registry — stores completed results keyed by run_id
# Sufficient for Phase 1 single-process deployment
_run_results: dict[str, PipelineResult] = {}
_run_status: dict[str, str] = {}   # "running" | "done" | "failed"


class GenerateLeadsRequest(BaseModel):
    context: BusinessContext


class StartRunResponse(BaseModel):
    pipeline_run_id: str
    status: str
    message: str


class RunStatusResponse(BaseModel):
    pipeline_run_id: str
    status: str                     # "running" | "done" | "failed"
    total_discovered: int = 0
    total_enriched: int = 0
    total_filtered_out: int = 0
    total_evaluated: int = 0
    total_rejected_by_icp: int = 0
    outreach_draft_count: int = 0
    error_count: int = 0
    errors: list[str] = []


class DraftsResponse(BaseModel):
    pipeline_run_id: str
    drafts: list[dict]


async def _run_pipeline(run_id: str, context: BusinessContext) -> None:
    """Background task — runs the full pipeline using the pre-assigned run_id."""
    try:
        _run_status[run_id] = "running"
        orchestrator = PipelineOrchestrator()
        result = await orchestrator.run(context, pipeline_run_id=run_id)
        _run_results[run_id] = result
        _run_status[run_id] = "done"
        logger.info("background.pipeline.done", run_id=run_id)
    except Exception as e:
        _run_status[run_id] = "failed"
        logger.error("background.pipeline.failed", run_id=run_id, error=str(e))


@router.post("/leads/generate", response_model=StartRunResponse)
async def generate_leads(
    request: GenerateLeadsRequest,
    background_tasks: BackgroundTasks,
) -> StartRunResponse:
    """
    Start the lead generation pipeline as a background task.
    Returns immediately with a run_id. Poll /leads/runs/{run_id} for status.

    Minimal request:
    { "context": { "industries": ["manufacturing"], "location": "Riyadh" } }

    Full request:
    {
      "context": {
        "industries": ["manufacturing", "logistics"],
        "location": "Riyadh",
        "country": "Saudi Arabia",
        "domain": "business transformation",
        "area": "King Abdullah Financial District",
        "excluded_categories": ["restaurant", "clinic"],
        "pain_points": ["operational inefficiency"],
        "value_proposition": "We help enterprises cut costs by 30% in 90 days.",
        "language_preference": "AUTO",
        "notes": "Focus on established B2B companies."
      }
    }
    """
    import uuid
    run_id = str(uuid.uuid4())
    _run_status[run_id] = "running"

    logger.info("api.generate_leads.start", location=request.context.location, run_id=run_id)
    background_tasks.add_task(_run_pipeline, run_id, request.context)

    return StartRunResponse(
        pipeline_run_id=run_id,
        status="running",
        message=f"Pipeline started. Poll GET /api/v1/leads/runs/{run_id} for status.",
    )


@router.get("/leads/runs/{run_id}", response_model=RunStatusResponse)
async def get_run_status(run_id: str) -> RunStatusResponse:
    """Poll for pipeline run status and summary counts."""
    status = _run_status.get(run_id)
    if status is None:
        # Check DB for runs from previous server sessions
        async with AsyncSessionLocal() as session:
            record = await session.get(PipelineRunRecord, run_id)
            if not record:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
            return RunStatusResponse(
                pipeline_run_id=run_id,
                status="done",
                total_discovered=record.total_discovered,
                total_enriched=record.total_enriched,
                total_filtered_out=record.total_filtered_out,
                total_evaluated=record.total_evaluated,
                total_rejected_by_icp=record.total_rejected_by_icp,
                outreach_draft_count=record.total_outreach_drafts,
            )

    result = _run_results.get(run_id)
    if result is None:
        return RunStatusResponse(pipeline_run_id=run_id, status=status)

    return RunStatusResponse(
        pipeline_run_id=run_id,
        status=status,
        total_discovered=result.total_discovered,
        total_enriched=result.total_enriched,
        total_filtered_out=result.total_filtered_out,
        total_evaluated=result.total_evaluated,
        total_rejected_by_icp=result.total_rejected_by_icp,
        outreach_draft_count=len(result.outreach_drafts),
        error_count=len(result.errors),
        errors=result.errors[:10],  # first 10 errors only
    )


@router.get("/leads/runs/{run_id}/drafts", response_model=DraftsResponse)
async def get_run_drafts(run_id: str) -> DraftsResponse:
    """Get all outreach drafts for a completed pipeline run."""
    async with AsyncSessionLocal() as session:
        stmt = select(OutreachRecord).where(OutreachRecord.pipeline_run_id == run_id)
        result = await session.execute(stmt)
        records = result.scalars().all()

    drafts = [
        {
            "lead_id": r.lead_id,
            "email_subject": r.email_subject,
            "email_body": r.email_body,
            "language": r.language,
            "word_count": r.word_count,
            "approved": r.approved,
        }
        for r in records
    ]
    return DraftsResponse(pipeline_run_id=run_id, drafts=drafts)


@router.get("/leads/runs/{run_id}/evaluated", response_model=dict)
async def get_run_evaluated(run_id: str) -> dict:
    """Get all evaluated leads for a completed pipeline run."""
    async with AsyncSessionLocal() as session:
        stmt = select(EvaluatedLeadRecord).where(EvaluatedLeadRecord.pipeline_run_id == run_id)
        result = await session.execute(stmt)
        records = result.scalars().all()

    leads = [
        {
            "lead_id": r.lead_id,
            "company_name": r.company_name,
            "location": r.location,
            "website": r.website,
            "fit_score": r.fit_score,
            "rule_score": r.rule_score,
            "llm_score": r.llm_score,
            "decision": r.decision,
            "llm_reasoning": r.llm_reasoning,
        }
        for r in records
    ]
    return {"pipeline_run_id": run_id, "evaluated_leads": leads}
