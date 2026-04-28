"""
Repository — all DB writes go through here.
One method per pipeline stage. Modules never touch SQLModel directly.

All datetime values are stripped of timezone info before insert because
SQLModel creates TIMESTAMP WITHOUT TIME ZONE columns by default.
"""

from __future__ import annotations
import json
from datetime import datetime


def _dt(dt: datetime | None) -> datetime | None:
    """Strip timezone → naive UTC. Returns None if input is None."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _now() -> datetime:
    return datetime.utcnow()


from app.schemas import RawLead, EnrichedLead, FilteredLead, EvaluatedLead, OutreachOutput
from app.storage.models import (
    PipelineRunRecord, RawLeadRecord, EnrichedLeadRecord,
    FilteredLeadRecord, EvaluatedLeadRecord, OutreachRecord,
)
from app.storage.database import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)


class LeadRepository:

    async def save_pipeline_run(self, result, context, completed_at: datetime | None = None) -> None:
        try:
            async with AsyncSessionLocal() as session:
                record = PipelineRunRecord(
                    id=result.pipeline_run_id,
                    location=context.location,
                    industries=", ".join(context.industries),
                    domain=context.domain,
                    country=getattr(context, "country", None),
                    area=context.area,
                    language_preference=context.language_preference.value,
                    total_discovered=result.total_discovered,
                    total_enriched=result.total_enriched,
                    total_filtered_out=result.total_filtered_out,
                    total_evaluated=result.total_evaluated,
                    total_rejected_by_icp=result.total_rejected_by_icp,
                    total_outreach_drafts=len(result.outreach_drafts),
                    started_at=_now(),
                    completed_at=_dt(completed_at) or _now(),
                    errors=json.dumps(result.errors),
                )
                session.add(record)
                await session.commit()
            logger.info("storage.saved_pipeline_run", run_id=result.pipeline_run_id)
        except Exception as e:
            logger.error("storage.save_pipeline_run.failed", error=str(e))

    async def save_raw(self, lead: RawLead) -> None:
        try:
            async with AsyncSessionLocal() as session:
                record = RawLeadRecord(
                    lead_id=str(lead.lead_id),
                    trace_id=str(lead.trace_id),
                    pipeline_run_id=str(lead.pipeline_run_id),
                    source=lead.source.value,
                    discovered_at=_dt(lead.discovered_at) or _now(),
                    company_name=lead.company_name,
                    location=lead.location,
                    category=lead.category,
                    website=str(lead.website) if lead.website else None,
                    phone=lead.phone,
                    address=lead.address,
                    rating=lead.rating,
                    review_count=lead.review_count,
                    google_maps_url=str(lead.google_maps_url) if lead.google_maps_url else None,
                    raw_json=lead.model_dump_json(),
                )
                session.add(record)
                await session.commit()
            logger.debug("storage.saved_raw", lead_id=str(lead.lead_id))
        except Exception as e:
            logger.warning("storage.save_raw.failed", lead_id=str(lead.lead_id), error=str(e))

    async def save_enriched(self, lead: EnrichedLead) -> None:
        try:
            async with AsyncSessionLocal() as session:
                record = EnrichedLeadRecord(
                    lead_id=str(lead.lead_id),
                    trace_id=str(lead.trace_id),
                    pipeline_run_id=str(lead.pipeline_run_id),
                    enriched_at=_dt(lead.enriched_at) or _now(),
                    company_name=lead.company_name,
                    location=lead.location,
                    website=str(lead.website) if lead.website else None,
                    enrichment_success=lead.enrichment_success,
                    summary=lead.summary,
                    industry=lead.industry,
                    business_type=lead.business_type.value,
                    services_detected=json.dumps(lead.services_detected),
                    key_people=json.dumps(lead.key_people),
                    contact_email=str(lead.contact_email) if lead.contact_email else None,
                    linkedin_url=str(lead.linkedin_url) if lead.linkedin_url else None,
                    founding_year=lead.founding_year,
                    language_of_website=lead.language_of_website,
                    enrichment_error=lead.enrichment_error,
                    raw_json=lead.model_dump_json(),
                )
                session.add(record)
                await session.commit()
            logger.debug("storage.saved_enriched", lead_id=str(lead.lead_id))
        except Exception as e:
            logger.warning("storage.save_enriched.failed", lead_id=str(lead.lead_id), error=str(e))

    async def save_filtered(self, lead: FilteredLead) -> None:
        try:
            async with AsyncSessionLocal() as session:
                record = FilteredLeadRecord(
                    lead_id=str(lead.lead_id),
                    trace_id=str(lead.trace_id),
                    pipeline_run_id=str(lead.pipeline_run_id),
                    filtered_at=_dt(lead.filtered_at) or _now(),
                    company_name=lead.company_name,
                    location=lead.location,
                    category=lead.category,
                    website=str(lead.website) if lead.website else None,
                    enrichment_success=lead.enrichment_success,
                    filter_reason=lead.filter_reason.value,
                    raw_json=lead.model_dump_json(),
                )
                session.add(record)
                await session.commit()
            logger.debug("storage.saved_filtered", lead_id=str(lead.lead_id))
        except Exception as e:
            logger.warning("storage.save_filtered.failed", lead_id=str(lead.lead_id), error=str(e))

    async def save_evaluated(self, lead: EvaluatedLead) -> None:
        try:
            async with AsyncSessionLocal() as session:
                record = EvaluatedLeadRecord(
                    lead_id=str(lead.lead_id),
                    trace_id=str(lead.trace_id),
                    pipeline_run_id=str(lead.pipeline_run_id),
                    evaluated_at=_dt(lead.evaluated_at) or _now(),
                    company_name=lead.company_name,
                    location=lead.location,
                    website=str(lead.website) if lead.website else None,
                    fit_score=lead.fit_score,
                    rule_score=lead.rule_score,
                    llm_score=lead.llm_score,
                    llm_was_called=lead.llm_was_called,
                    confidence_score=lead.confidence_score,
                    decision=lead.decision.value,
                    llm_reasoning=lead.llm_reasoning,
                    disqualification_reason=lead.disqualification_reason,
                    raw_json=lead.model_dump_json(),
                )
                session.add(record)
                await session.commit()
            logger.debug("storage.saved_evaluated", lead_id=str(lead.lead_id))
        except Exception as e:
            logger.warning("storage.save_evaluated.failed", lead_id=str(lead.lead_id), error=str(e))

    async def save_outreach(self, draft: OutreachOutput, inferred_pain_points: list[str] | None = None) -> None:
        try:
            async with AsyncSessionLocal() as session:
                record = OutreachRecord(
                    lead_id=str(draft.lead_id),
                    trace_id=str(draft.trace_id),
                    pipeline_run_id=str(draft.pipeline_run_id),
                    generated_at=_dt(draft.generated_at) or _now(),
                    email_subject=draft.email_subject,
                    email_body=draft.email_body,
                    language=draft.language.value,
                    word_count=draft.word_count,
                    inferred_pain_points=json.dumps(inferred_pain_points or []),
                    personalization_hooks=json.dumps(draft.personalization_hooks),
                    approved=draft.approved,
                )
                session.add(record)
                await session.commit()
            logger.debug("storage.saved_outreach", lead_id=str(draft.lead_id))
        except Exception as e:
            logger.warning("storage.save_outreach.failed", lead_id=str(draft.lead_id), error=str(e))
