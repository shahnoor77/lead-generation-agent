"""
Operational Visibility endpoints — Chunk 3

GET /api/v1/runs                        All pipeline runs with status summaries
GET /api/v1/runs/{run_id}/leads         All leads for a run (Kanban view)
GET /api/v1/leads/{lead_id}             Full lead detail (operator working screen)
GET /api/v1/runs/{run_id}/discovered    Raw+enriched leads with ICP decisions

Lead Discovery page:
GET /api/v1/discovery/leads             All leads across runs, filterable, sorted by ICP score

Lead Pipeline page:
GET /api/v1/pipeline/leads              Leads grouped by stage: new_leads, outreached, engaged
"""

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from typing import Optional
from app.schemas.operations import (
    PipelineRunsResponse,
    RunLeadsResponse,
    LeadDetailResponse,
)
from app.services.operations import OperationsService
from app.storage.database import AsyncSessionLocal
from app.storage.models import UserRecord
from app.api.dependencies import get_current_user

router = APIRouter()
_svc = OperationsService()


@router.get("/runs", response_model=PipelineRunsResponse)
async def get_all_runs(
    current_user: UserRecord = Depends(get_current_user),
) -> PipelineRunsResponse:
    """List all pipeline runs for the current user, newest first."""
    return await _svc.get_all_runs(user_id=current_user.id)


@router.get("/runs/{run_id}/leads", response_model=RunLeadsResponse)
async def get_run_leads(
    run_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> RunLeadsResponse:
    """Get all evaluated leads for a run owned by the current user."""
    return await _svc.get_run_leads(run_id, user_id=current_user.id)


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_lead_detail(
    lead_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> LeadDetailResponse:
    """Full operator view for a single lead (must belong to current user's run)."""
    return await _svc.get_lead_detail(lead_id, user_id=current_user.id)


@router.get("/runs/{run_id}/discovered")
async def get_run_discovered(
    run_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """All raw + enriched leads discovered in a run (current user only)."""
    from app.storage.ops_repository import OpsRepository
    from app.storage.models import EvaluatedLeadRecord
    from sqlmodel import select

    repo = OpsRepository()
    run = await repo.get_run(run_id, user_id=current_user.id)
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


# ── Lead Discovery Page ───────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel

class DiscoveryScanRequest(_BaseModel):
    """
    Simple 3-field input for the Lead Discovery page scan button.
    All fields optional — falls back to user's saved settings.
    """
    city: Optional[str] = None          # e.g. "Riyadh", "Karachi"
    industry: Optional[str] = None      # e.g. "manufacturing"
    company_size: Optional[str] = None  # "small" | "medium" | "large" (UI filter only, stored as note)


@router.post("/discovery/scan")
async def run_discovery_scan(
    body: DiscoveryScanRequest,
    background_tasks: BackgroundTasks,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Lead Discovery page — "Run Discovery Scan" button.

    Accepts city, industry, company_size. Starts a pipeline run in the background.
    Returns pipeline_run_id immediately — UI polls GET /api/v1/leads/runs/{run_id}
    then loads results via GET /api/v1/discovery/leads (no run_id needed — user-scoped).
    """
    import uuid as _uuid
    from datetime import datetime
    from app.schemas import BusinessContext
    from app.pipeline.orchestrator import PipelineOrchestrator
    from app.storage.database import AsyncSessionLocal
    from app.storage.models import PipelineRunRecord
    from app.services.settings import get_settings
    from app.api.routes.leads import _run_pipeline

    user_settings = await get_settings(current_user.id)
    ld = user_settings.lead_discovery

    # Resolve inputs — UI inputs override saved settings
    location = body.city or ld.location or "Saudi Arabia"
    industries = [body.industry] if body.industry else (ld.industries or ["manufacturing"])
    notes = ld.notes or ""
    if body.company_size:
        notes = f"Target company size: {body.company_size}. " + notes

    context = BusinessContext(
        location=location,
        country=ld.country,
        industries=industries,
        domain=ld.domain,
        area=body.city or ld.area,
        our_services=ld.our_services or [],
        value_proposition=ld.value_proposition,
        notes=notes.strip() or None,
        language_preference=ld.language_preference or "EN",
        sandbox_outreach=False,
    )

    run_id = str(_uuid.uuid4())

    async with AsyncSessionLocal() as session:
        session.add(PipelineRunRecord(
            id=run_id,
            user_id=current_user.id,
            location=location,
            industries=", ".join(industries),
            domain=ld.domain,
            country=ld.country,
            area=body.city or ld.area,
            language_preference=context.language_preference,
            started_at=datetime.utcnow(),
        ))
        await session.commit()

    background_tasks.add_task(_run_pipeline, run_id, context, current_user.id)

    return {
        "status": "started",
        "pipeline_run_id": run_id,
        "location": location,
        "industries": industries,
        "company_size_filter": body.company_size,
        "message": (
            "Discovery scan started. "
            "Poll GET /api/v1/leads/runs/{run_id} for status, "
            "then GET /api/v1/discovery/leads to view all results."
        ),
    }


@router.get("/discovery/leads")
async def get_discovery_leads(
    current_user: UserRecord = Depends(get_current_user),
    # Primary filters (match the scan form inputs)
    city: Optional[str] = Query(default=None, description="Filter by city (partial match on location)"),
    industry: Optional[str] = Query(default=None, description="Filter by industry (partial match)"),
    company_size: Optional[str] = Query(default=None, description="Filter by size: small | medium | large"),
    # Additional filters
    company: Optional[str] = Query(default=None, description="Filter by company name (partial match)"),
    min_icp_score: Optional[int] = Query(default=None, ge=0, le=100),
    source: Optional[str] = Query(default=None, description="google_maps | web_search"),
    run_id: Optional[str] = Query(default=None, description="Optionally scope to one run"),
    # Pagination
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """
    Lead Discovery page endpoint.

    Returns all discovered leads for the current user across all runs,
    enriched with ICP score, industry, revenue signals, location, and source.
    Ordered by ICP score descending, then discovered_at descending.

    Filters: industry, location, company name, min ICP score, source, run_id.

    Response fields per lead:
      lead_id, company_name, industry, location, city, website,
      contact_email, icp_score, icp_decision, revenue_signal,
      source, run_id, discovered_at, action (always "open")
    """
    from sqlmodel import select
    from app.storage.models import (
        PipelineRunRecord, RawLeadRecord, EnrichedLeadRecord, EvaluatedLeadRecord,
    )

    async with AsyncSessionLocal() as session:
        # Get all run IDs for this user
        run_q = select(PipelineRunRecord.id).where(PipelineRunRecord.user_id == current_user.id)
        if run_id:
            run_q = run_q.where(PipelineRunRecord.id == run_id)
        run_result = await session.execute(run_q)
        run_ids = [r[0] for r in run_result.all()]

        if not run_ids:
            return {"total": 0, "leads": [], "filters_applied": {}}

        # Load evaluated leads (have ICP scores)
        eval_q = (
            select(EvaluatedLeadRecord)
            .where(EvaluatedLeadRecord.pipeline_run_id.in_(run_ids))
            .order_by(EvaluatedLeadRecord.fit_score.desc())
        )
        if min_icp_score is not None:
            eval_q = eval_q.where(EvaluatedLeadRecord.fit_score >= min_icp_score)
        eval_result = await session.execute(eval_q)
        evaluated = list(eval_result.scalars().all())

        if not evaluated:
            return {"total": 0, "leads": [], "filters_applied": {}}

        lead_ids = [e.lead_id for e in evaluated]

        # Load enriched + raw in bulk
        enr_result = await session.execute(
            select(EnrichedLeadRecord).where(EnrichedLeadRecord.lead_id.in_(lead_ids))
        )
        enriched_map = {r.lead_id: r for r in enr_result.scalars().all()}

        raw_result = await session.execute(
            select(RawLeadRecord).where(RawLeadRecord.lead_id.in_(lead_ids))
        )
        raw_map = {r.lead_id: r for r in raw_result.scalars().all()}

    # Build + filter rows
    rows = []
    for ev in evaluated:
        enr = enriched_map.get(ev.lead_id)
        raw = raw_map.get(ev.lead_id)

        industry_val = (enr.industry if enr else None) or (raw.category if raw else None) or ""
        location_val = ev.location or ""
        company_val = ev.company_name or ""
        source_val = (raw.source if raw else "google_maps")

        # Apply text filters
        if industry and industry.lower() not in industry_val.lower():
            continue
        if city and city.lower() not in location_val.lower():
            continue
        if company and company.lower() not in company_val.lower():
            continue
        if source and source.lower() != source_val.lower():
            continue
        if company_size and revenue_signal != company_size.lower():
            continue
        # Revenue signal — derived from review count as proxy (no structured revenue data from scraping)
        review_count = raw.review_count if raw else None
        if review_count is None:
            revenue_signal = "unknown"
        elif review_count >= 100:
            revenue_signal = "large"
        elif review_count >= 20:
            revenue_signal = "medium"
        else:
            revenue_signal = "small"

        rows.append({
            "lead_id": ev.lead_id,
            "company_name": company_val,
            "industry": industry_val,
            "location": location_val,
            "website": ev.website,
            "contact_email": enr.contact_email if enr else None,
            "icp_score": ev.fit_score,
            "icp_decision": ev.decision,
            "revenue_signal": revenue_signal,
            "review_count": review_count,
            "source": source_val,
            "run_id": ev.pipeline_run_id,
            "discovered_at": (raw.discovered_at.isoformat() if raw and raw.discovered_at else
                              ev.evaluated_at.isoformat() if ev.evaluated_at else None),
            "action": "open",
        })

    total = len(rows)
    paginated = rows[offset: offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "leads": paginated,
        "filters_applied": {
            k: v for k, v in {
                "city": city,
                "industry": industry,
                "company_size": company_size,
                "company": company,
                "min_icp_score": min_icp_score,
                "source": source,
                "run_id": run_id,
            }.items() if v is not None
        },
    }


# ── Lead Pipeline Page ────────────────────────────────────────────────────────

@router.get("/pipeline/leads")
async def get_pipeline_leads(
    current_user: UserRecord = Depends(get_current_user),
    run_id: Optional[str] = Query(default=None, description="Filter to a specific run"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """
    Lead Pipeline page endpoint.

    Returns leads grouped into three stages:
      - new_leads:   DISCOVERED / ENRICHED / QUALIFIED / OUTREACH_DRAFTED / READY_FOR_REVIEW / READY_TO_SEND
      - outreached:  CONTACTED (initial email sent, no reply yet)
      - engaged:     REPLIED / MEETING_SCHEDULED / WON

    Each lead includes: company_name, industry, icp_score, location,
    contact_email, current_status, discovered_at, run_id.

    Also returns total counts per stage.
    """
    from sqlmodel import select
    from app.storage.models import (
        PipelineRunRecord, EvaluatedLeadRecord, EnrichedLeadRecord,
        RawLeadRecord, LeadLifecycleRecord,
    )

    NEW_STATUSES = {
        "DISCOVERED", "ENRICHED", "QUALIFIED",
        "OUTREACH_DRAFTED", "READY_FOR_REVIEW", "READY_TO_SEND",
    }
    OUTREACHED_STATUSES = {"CONTACTED"}
    ENGAGED_STATUSES = {"REPLIED", "MEETING_SCHEDULED", "WON"}

    async with AsyncSessionLocal() as session:
        run_q = select(PipelineRunRecord.id).where(PipelineRunRecord.user_id == current_user.id)
        if run_id:
            run_q = run_q.where(PipelineRunRecord.id == run_id)
        run_result = await session.execute(run_q)
        run_ids = [r[0] for r in run_result.all()]

        if not run_ids:
            return {
                "new_leads": [], "outreached": [], "engaged": [],
                "counts": {"new_leads": 0, "outreached": 0, "engaged": 0, "total": 0},
            }

        # Load lifecycle records for all leads in these runs
        lc_result = await session.execute(
            select(LeadLifecycleRecord)
            .where(LeadLifecycleRecord.pipeline_run_id.in_(run_ids))
        )
        lifecycle_rows = list(lc_result.scalars().all())

        if not lifecycle_rows:
            return {
                "new_leads": [], "outreached": [], "engaged": [],
                "counts": {"new_leads": 0, "outreached": 0, "engaged": 0, "total": 0},
            }

        lead_ids = [lc.lead_id for lc in lifecycle_rows]
        lc_map = {lc.lead_id: lc for lc in lifecycle_rows}

        # Load evaluated leads for ICP scores
        eval_result = await session.execute(
            select(EvaluatedLeadRecord).where(EvaluatedLeadRecord.lead_id.in_(lead_ids))
        )
        eval_map = {r.lead_id: r for r in eval_result.scalars().all()}

        # Load enriched for industry + contact
        enr_result = await session.execute(
            select(EnrichedLeadRecord).where(EnrichedLeadRecord.lead_id.in_(lead_ids))
        )
        enr_map = {r.lead_id: r for r in enr_result.scalars().all()}

        # Load raw for discovered_at
        raw_result = await session.execute(
            select(RawLeadRecord).where(RawLeadRecord.lead_id.in_(lead_ids))
        )
        raw_map = {r.lead_id: r for r in raw_result.scalars().all()}

    def _build_lead_row(lc: LeadLifecycleRecord) -> dict:
        ev = eval_map.get(lc.lead_id)
        enr = enr_map.get(lc.lead_id)
        raw = raw_map.get(lc.lead_id)
        return {
            "lead_id": lc.lead_id,
            "company_name": lc.company_name,
            "industry": (enr.industry if enr else None) or (raw.category if raw else None),
            "icp_score": ev.fit_score if ev else None,
            "location": ev.location if ev else (raw.location if raw else None),
            "contact_email": enr.contact_email if enr else None,
            "current_status": lc.current_status,
            "status_updated_at": lc.status_updated_at.isoformat() if lc.status_updated_at else None,
            "discovered_at": (raw.discovered_at.isoformat() if raw and raw.discovered_at else None),
            "run_id": lc.pipeline_run_id,
        }

    new_leads = []
    outreached = []
    engaged = []

    for lc in lifecycle_rows:
        status = lc.current_status
        row = _build_lead_row(lc)
        if status in NEW_STATUSES:
            new_leads.append(row)
        elif status in OUTREACHED_STATUSES:
            outreached.append(row)
        elif status in ENGAGED_STATUSES:
            engaged.append(row)
        # LOST / ARCHIVED excluded from pipeline view

    # Sort each group by ICP score desc, then discovered_at desc
    def _sort_key(r: dict):
        return (-(r["icp_score"] or 0), r["discovered_at"] or "")

    new_leads.sort(key=_sort_key)
    outreached.sort(key=_sort_key)
    engaged.sort(key=_sort_key)

    # Apply limit per group
    new_leads = new_leads[:limit]
    outreached = outreached[:limit]
    engaged = engaged[:limit]

    total = len(new_leads) + len(outreached) + len(engaged)

    return {
        "new_leads": new_leads,
        "outreached": outreached,
        "engaged": engaged,
        "counts": {
            "new_leads": len(new_leads),
            "outreached": len(outreached),
            "engaged": len(engaged),
            "total": total,
        },
    }
