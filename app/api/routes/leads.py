"""
Lead generation endpoints — auth-protected.

POST /api/v1/leads/generate          Start pipeline (saves config, auto-restarts)
GET  /api/v1/leads/runs/{run_id}     Poll run status
GET  /api/v1/leads/runs/{run_id}/drafts
GET  /api/v1/leads/runs/{run_id}/evaluated
DELETE /api/v1/leads/continuous/{config_id}  Stop continuous loop
GET  /api/v1/leads/continuous        List active continuous runs
GET  /api/v1/auth/config             Load saved config for current user
"""

import asyncio
import os
import uuid as _uuid
from collections.abc import Callable
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel

from app.schemas import BusinessContext
from app.pipeline import PipelineOrchestrator, PipelineResult
from app.storage.database import AsyncSessionLocal
from app.storage.models import PipelineRunRecord, OutreachRecord, EvaluatedLeadRecord, UserRecord
from app.core.logging import get_logger
from app.api.dependencies import get_current_user
from app.services.user_config import save_user_config, load_user_config
from app.core.config import settings as app_settings
from app.services.sandbox_outreach import count_active_inboxes
from sqlmodel import select

router = APIRouter()
logger = get_logger(__name__)

_run_results: dict[str, PipelineResult] = {}
_run_status: dict[str, str] = {}
_continuous_active: dict[str, bool] = {}
_continuous_user: dict[str, str] = {}   # config_id → user_id (UUID)


class GenerateLeadsRequest(BaseModel):
    context: BusinessContext


class StartRunResponse(BaseModel):
    pipeline_run_id: str
    status: str
    message: str


class RunStatusResponse(BaseModel):
    pipeline_run_id: str
    status: str
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


# ── Pipeline runner ───────────────────────────────────────────────────────────

async def _inbox_poll_until(
    user_id: str,
    should_stop: Callable[[], bool],
    *,
    tag: str = "inbox",
) -> None:
    """
    Periodically scans the sender inbox for outbound-thread replies while lead-gen runs elsewhere.
    Uses asyncio (not OS threads): I/O runs in thread executor inside outreach agent IMAP helpers.
    """
    from app.modules.outreach.agent import run_followup_inbox_only

    poll_seconds = float(os.environ.get("OUTREACH_INBOX_POLL_INTERVAL_SEC", "20"))
    poll_seconds = max(10.0, min(poll_seconds, 3600.0))
    logger.info("inbox.poll_loop_started", user_id=user_id, tag=tag, interval_seconds=poll_seconds)

    while not should_stop():
        try:
            summary = await run_followup_inbox_only(user_id)
            if isinstance(summary, dict) and summary.get("processed"):
                logger.info(
                    "inbox.poll_processed",
                    user_id=user_id,
                    tag=tag,
                    processed=summary.get("processed"),
                    closed=summary.get("closed"),
                    auto_replied=summary.get("auto_replied"),
                )
        except Exception as e:
            logger.warning("inbox.poll_error", user_id=user_id, tag=tag, error=str(e)[:200])

        slept = 0.0
        while slept < poll_seconds and not should_stop():
            chunk = min(10.0, poll_seconds - slept)
            await asyncio.sleep(chunk)
            slept += chunk

    logger.info("inbox.poll_loop_stopped", user_id=user_id, tag=tag)


async def _run_pipeline(
    run_id: str,
    context: BusinessContext,
    user_id: str | None = None,
    *,
    companion_inbox_poll: bool = True,
) -> None:
    """
    Runs the enrichment / ICP pipeline. Optionally runs an inbox polling task in parallel so
    follow-up replies are detected while discovery + enrichment blocks this coroutine.
    """
    cancel_inbox_buddy = asyncio.Event()
    inbox_buddy_task: asyncio.Task | None = None
    if user_id is not None and companion_inbox_poll:
        inbox_buddy_task = asyncio.create_task(
            _inbox_poll_until(
                user_id,
                lambda: cancel_inbox_buddy.is_set(),
                tag=f"pipeline_run_{run_id}",
            ),
        )

    try:
        _run_status[run_id] = "running"
        orchestrator = PipelineOrchestrator()
        result = await orchestrator.run(context, pipeline_run_id=run_id, user_id=user_id)
        _run_results[run_id] = result
        _run_status[run_id] = "done"
        logger.info("background.pipeline.done", run_id=run_id, user_id=user_id)
    except Exception as e:
        _run_status[run_id] = "failed"
        logger.error("background.pipeline.failed", run_id=run_id, error=str(e))
    finally:
        cancel_inbox_buddy.set()
        if inbox_buddy_task is not None:
            inbox_buddy_task.cancel()
            try:
                await inbox_buddy_task
            except asyncio.CancelledError:
                pass


async def _continuous_loop(config_id: str, context: BusinessContext, user_id: str) -> None:
    """
    Runs the pipeline repeatedly until cancelled or config changes.
    Cross-run dedup in DiscoveryService ensures no duplicate leads.
    """
    interval_seconds = context.continuous_interval_minutes * 60
    logger.info("continuous.started", config_id=config_id, user_id=user_id,
                interval_minutes=context.continuous_interval_minutes)

    # One inbox poller for the whole continuous session (parallel to every pipeline iteration).
    followup_poller = asyncio.create_task(
        _inbox_poll_until(
            user_id,
            lambda: not _continuous_active.get(config_id, False),
            tag=f"continuous_{config_id}",
        ),
    )

    try:
        while _continuous_active.get(config_id, False):
            run_id = str(_uuid.uuid4())
            logger.info("continuous.run_starting", config_id=config_id, run_id=run_id)
            await _run_pipeline(run_id, context, user_id=user_id, companion_inbox_poll=False)

            if not _continuous_active.get(config_id, False):
                break

            logger.info("continuous.waiting", config_id=config_id, seconds=interval_seconds)
            for _ in range(interval_seconds // 10):
                if not _continuous_active.get(config_id, False):
                    break
                await asyncio.sleep(10)
    finally:
        followup_poller.cancel()
        try:
            await followup_poller
        except asyncio.CancelledError:
            pass

    logger.info("continuous.stopped", config_id=config_id)
    _continuous_active.pop(config_id, None)
    _continuous_user.pop(config_id, None)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/leads/generate", response_model=StartRunResponse)
async def generate_leads(
    request: GenerateLeadsRequest,
    background_tasks: BackgroundTasks,
    current_user: UserRecord = Depends(get_current_user),
) -> StartRunResponse:
    """
    Start a lead generation pipeline run.
    Saves the configuration for this user (restored on next form load).
    If continuous=True, auto-restarts after each run until stopped.
    """
    # Persist config for this user
    await save_user_config(current_user.id, request.context)

    if request.context.sandbox_outreach:
        if not app_settings.sandbox_outreach_enabled:
            raise HTTPException(
                status_code=403,
                detail="Sandbox outreach is disabled on this deployment.",
            )
        if request.context.continuous:
            raise HTTPException(
                status_code=400,
                detail="Sandbox pipeline runs cannot use continuous mode.",
            )
        if await count_active_inboxes(current_user.id) < 1:
            raise HTTPException(
                status_code=400,
                detail="Add at least one sandbox test inbox (Settings) before running a sandbox pipeline.",
            )

    run_id = str(_uuid.uuid4())
    _run_status[run_id] = "running"
    logger.info("api.generate_leads.start", location=request.context.location,
                run_id=run_id, user_id=current_user.id)

    if request.context.continuous:
        config_id = run_id
        _continuous_active[config_id] = True
        _continuous_user[config_id] = current_user.id
        background_tasks.add_task(_continuous_loop, config_id, request.context, current_user.id)
        return StartRunResponse(
            pipeline_run_id=run_id,
            status="running",
            message=(
                f"Continuous pipeline started (every {request.context.continuous_interval_minutes} min). "
                f"Stop via DELETE /api/v1/leads/continuous/{config_id}"
            ),
        )

    background_tasks.add_task(_run_pipeline, run_id, request.context, current_user.id)
    return StartRunResponse(
        pipeline_run_id=run_id,
        status="running",
        message=f"Pipeline started. Poll GET /api/v1/leads/runs/{run_id} for status.",
    )


@router.get("/leads/runs/{run_id}", response_model=RunStatusResponse)
async def get_run_status(
    run_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> RunStatusResponse:
    status = _run_status.get(run_id)
    if status is None:
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
        errors=result.errors[:10],
    )


@router.get("/leads/runs/{run_id}/drafts", response_model=DraftsResponse)
async def get_run_drafts(
    run_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> DraftsResponse:
    async with AsyncSessionLocal() as session:
        stmt = select(OutreachRecord).where(OutreachRecord.pipeline_run_id == run_id)
        result = await session.execute(stmt)
        records = result.scalars().all()
    drafts = [
        {"lead_id": r.lead_id, "email_subject": r.email_subject,
         "email_body": r.email_body, "language": r.language,
         "word_count": r.word_count, "approved": r.approved}
        for r in records
    ]
    return DraftsResponse(pipeline_run_id=run_id, drafts=drafts)


@router.get("/leads/runs/{run_id}/evaluated")
async def get_run_evaluated(
    run_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        stmt = select(EvaluatedLeadRecord).where(EvaluatedLeadRecord.pipeline_run_id == run_id)
        result = await session.execute(stmt)
        records = result.scalars().all()
    leads = [
        {"lead_id": r.lead_id, "company_name": r.company_name, "location": r.location,
         "website": r.website, "fit_score": r.fit_score, "decision": r.decision}
        for r in records
    ]
    return {"pipeline_run_id": run_id, "evaluated_leads": leads}


@router.delete("/leads/continuous/{config_id}")
async def stop_continuous(
    config_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    if config_id not in _continuous_active:
        raise HTTPException(status_code=404, detail=f"No active continuous run {config_id}")
    # Only the owner can stop it
    if _continuous_user.get(config_id) != current_user.id:
        raise HTTPException(status_code=403, detail="Not your continuous run")
    _continuous_active[config_id] = False
    return {"config_id": config_id, "status": "stopping"}


@router.get("/leads/continuous")
async def list_continuous(current_user: UserRecord = Depends(get_current_user)) -> dict:
    active = [k for k, v in _continuous_active.items()
              if v and _continuous_user.get(k) == current_user.id]
    return {"active_continuous_runs": active, "count": len(active)}


@router.get("/leads/config")
async def get_saved_config(current_user: UserRecord = Depends(get_current_user)) -> dict:
    """Return the user's last-saved lead generation configuration."""
    config = await load_user_config(current_user.id)
    return {"config": config}
