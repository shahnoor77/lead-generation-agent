"""
User Settings endpoints.

GET  /api/v1/settings                  Get current user's settings
PUT  /api/v1/settings                  Save/update settings (partial update supported)
POST /api/v1/settings/generate-leads   Start a lead generation run using saved settings
POST /api/v1/settings/test-sandbox     Trigger a sandbox (test) outreach run using saved settings
"""

from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.schemas.settings import UserSettingsRequest, UserSettingsResponse
from app.services.settings import get_settings, save_settings
from app.api.dependencies import get_current_user
from app.storage.models import UserRecord
from app.core.logging import get_logger

router = APIRouter(tags=["settings"])
logger = get_logger(__name__)


@router.get("/settings", response_model=UserSettingsResponse)
async def get_user_settings(
    current_user: UserRecord = Depends(get_current_user),
) -> UserSettingsResponse:
    """Get current user's ICP, outreach, and AI agent settings."""
    return await get_settings(current_user.id)


@router.put("/settings", response_model=UserSettingsResponse)
async def update_user_settings(
    body: UserSettingsRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> UserSettingsResponse:
    """
    Save user settings. All groups are optional — only provided groups are updated.

    Example (update ICP only):
    {
      "icp": {
        "decision_maker_titles": ["CEO", "COO", "GM"],
        "min_fit_score": 55,
        "require_website": true,
        "scoring_weights": {
          "industry_match": 40,
          "revenue_fit": 15,
          "location": 25,
          "digital_presence": 10,
          "firmographic_quality": 10
        }
      }
    }
    """
    return await save_settings(current_user.id, body)


class GenerateLeadsRequest(BaseModel):
    """
    Optional overrides for a quick lead generation run from the Settings page.
    If not provided, values are pulled from the user's saved ICP settings.
    """
    location: Optional[str] = None
    country: Optional[str] = None
    industries: Optional[list[str]] = None
    domain: Optional[str] = None
    area: Optional[str] = None
    our_services: Optional[list[str]] = None
    value_proposition: Optional[str] = None
    notes: Optional[str] = None
    language_preference: Optional[str] = None


@router.post("/settings/generate-leads")
async def generate_leads_from_settings(
    body: GenerateLeadsRequest,
    background_tasks: BackgroundTasks,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Start a lead generation pipeline run using the user's saved settings.
    Overrides can be passed in the request body; everything else defaults to saved ICP settings.
    Returns a run_id immediately — poll /api/v1/leads/runs/{run_id} for status.
    """
    from app.schemas import BusinessContext
    from app.pipeline.orchestrator import PipelineOrchestrator
    from app.storage.database import AsyncSessionLocal
    from app.storage.models import PipelineRunRecord
    from datetime import datetime

    user_settings = await get_settings(current_user.id)
    icp = user_settings.icp
    ld = user_settings.lead_discovery

    # Build context from saved settings + optional overrides
    location = body.location or ld.location or icp.primary_geography or "Saudi Arabia"
    industries = body.industries or ld.industries or icp.target_industries or ["manufacturing"]

    context = BusinessContext(
        location=location,
        country=body.country or ld.country,
        industries=industries,
        domain=body.domain or ld.domain,
        area=body.area or ld.area,
        our_services=body.our_services or ld.our_services or [],
        value_proposition=body.value_proposition or ld.value_proposition,
        notes=body.notes or ld.notes,
        language_preference=body.language_preference or ld.language_preference or user_settings.outreach.language_default or "EN",
        sandbox_outreach=False,
    )

    run_id = str(uuid.uuid4())

    # Persist run record immediately so frontend can poll
    async with AsyncSessionLocal() as session:
        session.add(PipelineRunRecord(
            id=run_id,
            user_id=current_user.id,
            location=location,
            industries=", ".join(industries),
            domain=body.domain,
            country=body.country,
            area=body.area,
            language_preference=context.language_preference,
            started_at=datetime.utcnow(),
        ))
        await session.commit()

    orchestrator = PipelineOrchestrator()
    background_tasks.add_task(
        orchestrator.run,
        context,
        pipeline_run_id=run_id,
        user_id=current_user.id,
    )

    logger.info("settings.generate_leads.started", user_id=current_user.id, run_id=run_id)
    return {
        "status": "started",
        "pipeline_run_id": run_id,
        "message": "Lead generation started using your saved settings. Poll /api/v1/leads/runs/{run_id} for status.",
        "location": location,
        "industries": industries,
    }


@router.post("/settings/test-sandbox")
async def test_sandbox_from_settings(
    body: GenerateLeadsRequest,
    background_tasks: BackgroundTasks,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Start a sandbox (test) lead generation + outreach run.
    Outbound emails are routed to your configured sandbox test inboxes instead of real leads.
    Requires at least one sandbox inbox configured under Outreach → Sandbox Test Inboxes.
    """
    from app.schemas import BusinessContext
    from app.pipeline.orchestrator import PipelineOrchestrator
    from app.storage.database import AsyncSessionLocal
    from app.storage.models import PipelineRunRecord, SandboxTestInboxRecord
    from sqlmodel import select
    from datetime import datetime
    from app.core.config import settings as app_settings

    if not app_settings.sandbox_outreach_enabled:
        raise HTTPException(status_code=400, detail="Sandbox outreach is disabled on this server.")

    # Verify at least one sandbox inbox is configured
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SandboxTestInboxRecord)
            .where(SandboxTestInboxRecord.user_id == current_user.id)
            .where(SandboxTestInboxRecord.is_active == True)
            .limit(1)
        )
        inbox = result.scalar_one_or_none()

    if not inbox:
        raise HTTPException(
            status_code=400,
            detail="No sandbox test inboxes configured. Add at least one in Settings → Sandbox Test Inboxes.",
        )

    user_settings = await get_settings(current_user.id)
    icp = user_settings.icp
    ld = user_settings.lead_discovery

    location = body.location or ld.location or icp.primary_geography or "Saudi Arabia"
    industries = body.industries or ld.industries or icp.target_industries or ["manufacturing"]

    context = BusinessContext(
        location=location,
        country=body.country or ld.country,
        industries=industries,
        domain=body.domain or ld.domain,
        area=body.area or ld.area,
        our_services=body.our_services or ld.our_services or [],
        value_proposition=body.value_proposition or ld.value_proposition,
        notes=body.notes or ld.notes,
        language_preference=body.language_preference or ld.language_preference or user_settings.outreach.language_default or "EN",
        sandbox_outreach=True,
    )

    run_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as session:
        session.add(PipelineRunRecord(
            id=run_id,
            user_id=current_user.id,
            location=location,
            industries=", ".join(industries),
            domain=body.domain,
            country=body.country,
            area=body.area,
            language_preference=context.language_preference,
            sandbox_outreach=True,
            started_at=datetime.utcnow(),
        ))
        await session.commit()

    orchestrator = PipelineOrchestrator()
    background_tasks.add_task(
        orchestrator.run,
        context,
        pipeline_run_id=run_id,
        user_id=current_user.id,
    )

    logger.info("settings.test_sandbox.started", user_id=current_user.id, run_id=run_id,
                sandbox_inbox=inbox.email)
    return {
        "status": "started",
        "pipeline_run_id": run_id,
        "sandbox": True,
        "sandbox_inbox": inbox.email,
        "message": "Sandbox test run started. Emails will be routed to your test inboxes.",
        "location": location,
        "industries": industries,
    }
