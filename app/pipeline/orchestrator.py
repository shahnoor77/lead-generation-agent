"""
Pipeline Orchestrator — wires all stages, persists every stage to PostgreSQL.

Two workflow modes (set in user AI Agent settings):

  semi-autonomous:
    Pipeline runs Discovery → Enrichment → Filter → ICP → Draft Generation.
    Stops there. Operator reviews editable drafts, manually approves each one,
    then manually triggers send via the outreach button.

  autonomous:
    Pipeline runs all stages end-to-end including auto-send.
    Drafts are generated with higher quality settings (lower temperature,
    more retries). Auto-approved and sent immediately after generation.
    No human review step — operator trusts the system.
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
    agent_mode: str = "semi-autonomous"
    total_discovered: int = 0
    total_enriched: int = 0
    total_filtered_out: int = 0
    total_evaluated: int = 0
    total_rejected_by_icp: int = 0
    total_auto_sent: int = 0
    outreach_drafts: list = field(default_factory=list)
    evaluated_leads: list = field(default_factory=list)
    filtered_leads: list = field(default_factory=list)
    errors: list = field(default_factory=list)


async def _load_agent_mode(user_id: int | None) -> str:
    """Load the user's agent_mode setting. Defaults to semi-autonomous."""
    if user_id is None:
        return "semi-autonomous"
    try:
        from app.services.settings import get_settings
        s = await get_settings(user_id)
        return s.ai_agent.agent_mode
    except Exception:
        return "semi-autonomous"


class PipelineOrchestrator:
    def __init__(self) -> None:
        self._discovery = DiscoveryService()
        self._enrichment = EnrichmentService()
        self._filter = FilterService()
        self._icp = ICPEvaluationService()
        self._outreach = OutreachService()
        self._repo = LeadRepository()
        self._lifecycle = LeadLifecycleService()

    async def run(
        self,
        context: BusinessContext,
        pipeline_run_id: str | None = None,
        user_id: int | None = None,
    ) -> PipelineResult:
        if pipeline_run_id:
            run_id = pipeline_run_id
            run_uuid = uuid.UUID(run_id)
        else:
            run_uuid = uuid.uuid4()
            run_id = str(run_uuid)

        agent_mode = await _load_agent_mode(user_id)
        is_autonomous = agent_mode == "autonomous"

        result = PipelineResult(pipeline_run_id=run_id, agent_mode=agent_mode)
        seen_ids: set = set()

        structlog.contextvars.bind_contextvars(pipeline_run_id=run_id)
        logger.info("pipeline.start", location=context.location,
                    industries=context.industries, agent_mode=agent_mode)

        # ── Stage 1: Discovery ──────────────────────────────────────────────
        raw_leads = await self._discovery.discover(context, pipeline_run_id=run_uuid, user_id=user_id)
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

            # Stage 5: Outreach Generation
            try:
                draft = await self._outreach.generate(
                    enriched, evaluated, context,
                    user_id=user_id,
                    autonomous=is_autonomous,
                )
                if draft:
                    result.outreach_drafts.append(draft)
                    await self._repo.save_outreach(draft)
                    await self._lifecycle.set_pipeline_status(
                        str(draft.lead_id), evaluated.company_name, run_id, LeadLifecycleStatus.OUTREACH_DRAFTED
                    )

                    # ── Autonomous mode: auto-approve + auto-send ──────────
                    if is_autonomous and draft:
                        sent = await self._auto_send(
                            draft=draft,
                            enriched=enriched,
                            user_id=user_id,
                            run_id=run_id,
                            company_name=evaluated.company_name,
                        )
                        if sent:
                            result.total_auto_sent += 1

            except Exception as e:
                result.errors.append(f"outreach:{enriched.lead_id}:{e}")
                logger.error("pipeline.outreach.error", error=str(e))

        # ── Persist run summary ─────────────────────────────────────────────
        structlog.contextvars.clear_contextvars()
        await self._repo.save_pipeline_run(
            result, context, completed_at=datetime.utcnow(), user_id=user_id
        )

        logger.info(
            "pipeline.complete",
            run_id=run_id,
            agent_mode=agent_mode,
            discovered=result.total_discovered,
            enriched=result.total_enriched,
            filtered_out=result.total_filtered_out,
            evaluated=result.total_evaluated,
            rejected_by_icp=result.total_rejected_by_icp,
            drafts=len(result.outreach_drafts),
            auto_sent=result.total_auto_sent,
            errors=len(result.errors),
        )
        return result

    async def _auto_send(
        self,
        draft: OutreachOutput,
        enriched,
        user_id: int | None,
        run_id: str,
        company_name: str,
    ) -> bool:
        """
        Autonomous mode: auto-approve the draft and send immediately.
        Returns True if sent successfully.
        """
        if user_id is None:
            return False

        try:
            from app.storage.database import AsyncSessionLocal
            from app.storage.models import FinalizedDraftRecord, SenderEmailAccountRecord
            from app.modules.outreach.agent import (
                _already_sent, _send_email_async, _log_sent, _mark_contacted,
            )
            from app.utils.encryption import decrypt
            from sqlmodel import select

            # Need a finalized draft record with receiver email
            receiver_email = str(enriched.contact_email) if enriched.contact_email else None
            if not receiver_email:
                logger.info("auto_send.no_receiver_email", lead_id=str(draft.lead_id))
                return False

            lead_id = str(draft.lead_id)

            # Dedup check
            if await _already_sent(user_id, lead_id, receiver_email):
                logger.info("auto_send.already_sent", lead_id=lead_id)
                return False

            # Load sender account
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SenderEmailAccountRecord)
                    .where(SenderEmailAccountRecord.user_id == user_id)
                    .where(SenderEmailAccountRecord.is_active == True)
                    .limit(1)
                )
                sender = result.scalar_one_or_none()

            if not sender:
                logger.warning("auto_send.no_sender_account", user_id=user_id)
                return False

            smtp_password = decrypt(sender.smtp_password_encrypted)

            await _send_email_async(
                smtp_host=sender.smtp_host,
                smtp_port=sender.smtp_port,
                smtp_username=sender.smtp_username,
                smtp_password=smtp_password,
                use_tls=sender.use_tls,
                from_email=sender.email_address,
                from_name=sender.display_name or sender.email_address,
                to_email=receiver_email,
                subject=draft.email_subject,
                body=draft.email_body,
            )

            await _log_sent(user_id, lead_id, sender.email_address,
                           receiver_email, draft.email_subject)
            await _mark_contacted(lead_id, user_id)

            logger.info("auto_send.sent", lead_id=lead_id, to=receiver_email,
                       company=company_name)
            return True

        except Exception as e:
            logger.error("auto_send.failed", lead_id=str(draft.lead_id), error=str(e)[:200])
            return False

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

    async def run(self, context: BusinessContext, pipeline_run_id: str | None = None, user_id: int | None = None) -> PipelineResult:
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
        raw_leads = await self._discovery.discover(context, pipeline_run_id=run_uuid, user_id=user_id)
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
                draft = await self._outreach.generate(enriched, evaluated, context, user_id=user_id)
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
        await self._repo.save_pipeline_run(result, context, completed_at=datetime.utcnow(), user_id=user_id)

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
