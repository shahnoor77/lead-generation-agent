"""
Pipeline Orchestrator — wires all stages, persists every stage to PostgreSQL.
"""

from __future__ import annotations
import uuid
from datetime import datetime
import structlog.contextvars
from dataclasses import dataclass, field

from app.schemas import (
    BusinessContext, EvaluatedLead, FilteredLead, ICPDecision, OutreachOutput,
)
from app.modules.discovery import DiscoveryService
from app.modules.enrichment import EnrichmentService
from app.modules.filter import FilterService
from app.modules.icp import ICPEvaluationService
from app.modules.outreach import OutreachService
from app.storage.repository import LeadRepository
from app.services.lifecycle import LeadLifecycleService
from app.schemas.lifecycle import LeadLifecycleStatus
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    pipeline_run_id: str
    total_discovered: int = 0
    total_enriched: int = 0
    total_filtered_out: int = 0
    total_evaluated: int = 0
    total_rejected_by_icp: int = 0
    outreach_drafts: list = field(default_factory=list)
    evaluated_leads: list = field(default_factory=list)
    filtered_leads: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class PipelineOrchestrator:
    def __init__(self) -> None:
        self._discovery = DiscoveryService()
        self._enrichment = EnrichmentService()
        self._filter = FilterService()
        self._icp = ICPEvaluationService()
        self._outreach = OutreachService()
        self._repo = LeadRepository()
        self._lifecycle = LeadLifecycleService()

    async def run(self, context: BusinessContext, pipeline_run_id: str | None = None) -> PipelineResult:
        if pipeline_run_id:
            run_id = pipeline_run_id
            run_uuid = uuid.UUID(run_id)
        else:
            run_uuid = uuid.uuid4()
            run_id = str(run_uuid)

        result = PipelineResult(pipeline_run_id=run_id)
        seen_ids: set = set()

        structlog.contextvars.bind_contextvars(pipeline_run_id=run_id)
        logger.info("pipeline.start", location=context.location, industries=context.industries)

        # ── Stage 1: Discovery ──────────────────────────────────────────────
        raw_leads = await self._discovery.discover(context, pipeline_run_id=run_uuid)
        result.total_discovered = len(raw_leads)
        logger.info("pipeline.discovery.done", count=result.total_discovered)

        for raw in raw_leads:
            await self._repo.save_raw(raw)
            await self._lifecycle.set_pipeline_status(
                str(raw.lead_id), raw.company_name, run_id, LeadLifecycleStatus.DISCOVERED
            )

        # ── Stage 2: Enrichment ─────────────────────────────────────────────
        enriched_leads = []
        for raw in raw_leads:
            structlog.contextvars.bind_contextvars(
                lead_id=str(raw.lead_id), trace_id=str(raw.trace_id)
            )
            try:
                enriched = await self._enrichment.enrich(raw)
                enriched_leads.append(enriched)
                result.total_enriched += 1
                await self._repo.save_enriched(enriched)
                await self._lifecycle.set_pipeline_status(
                    str(enriched.lead_id), enriched.company_name, run_id, LeadLifecycleStatus.ENRICHED
                )
            except Exception as e:
                result.errors.append(f"enrichment:{raw.lead_id}:{e}")
                logger.error("pipeline.enrichment.error", error=str(e))

        # ── Stage 3: Filter ─────────────────────────────────────────────────
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(pipeline_run_id=run_id)

        passlist, rejectlist = self._filter.apply(enriched_leads, context, seen_ids)
        result.total_filtered_out = len(rejectlist)
        result.filtered_leads = rejectlist

        for rejected in rejectlist:
            await self._repo.save_filtered(rejected)

        logger.info("pipeline.filter.done", passed=len(passlist), rejected=len(rejectlist))

        # ── Stages 4 + 5: ICP → Outreach ───────────────────────────────────
        for enriched in passlist:
            structlog.contextvars.bind_contextvars(
                lead_id=str(enriched.lead_id), trace_id=str(enriched.trace_id)
            )

            # Stage 4: ICP Evaluation
            try:
                evaluated = await self._icp.evaluate(enriched, context)
                result.total_evaluated += 1
                result.evaluated_leads.append(evaluated)
                await self._repo.save_evaluated(evaluated)

                if evaluated.decision == ICPDecision.REJECTED:
                    result.total_rejected_by_icp += 1
                    continue

                await self._lifecycle.set_pipeline_status(
                    str(evaluated.lead_id), evaluated.company_name, run_id, LeadLifecycleStatus.QUALIFIED
                )
            except Exception as e:
                result.errors.append(f"icp:{enriched.lead_id}:{e}")
                logger.error("pipeline.icp.error", error=str(e))
                continue

            # Stage 5: Outreach Generation (QUALIFIED only)
            try:
                draft = await self._outreach.generate(enriched, evaluated, context)
                if draft:
                    result.outreach_drafts.append(draft)
                    await self._repo.save_outreach(draft)
                    await self._lifecycle.set_pipeline_status(
                        str(draft.lead_id), evaluated.company_name, run_id, LeadLifecycleStatus.OUTREACH_DRAFTED
                    )
            except Exception as e:
                result.errors.append(f"outreach:{enriched.lead_id}:{e}")
                logger.error("pipeline.outreach.error", error=str(e))

        # ── Persist run summary ─────────────────────────────────────────────
        structlog.contextvars.clear_contextvars()
        await self._repo.save_pipeline_run(result, context, completed_at=datetime.utcnow())

        logger.info(
            "pipeline.complete",
            run_id=run_id,
            discovered=result.total_discovered,
            enriched=result.total_enriched,
            filtered_out=result.total_filtered_out,
            evaluated=result.total_evaluated,
            rejected_by_icp=result.total_rejected_by_icp,
            drafts=len(result.outreach_drafts),
            errors=len(result.errors),
        )
        return result
