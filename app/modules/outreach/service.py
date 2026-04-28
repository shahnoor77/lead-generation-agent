"""
Outreach Generation Module
--------------------------
Responsibility: Generate a culturally-aware, personalized outreach draft.
Input:  EnrichedLead + EvaluatedLead + BusinessContext
Output: OutreachOutput

Rules:
- Only called for ICPDecision.QUALIFIED leads
- approved is always False — human must review before any send
- Language follows context.language_preference

Failure strategy:
- LLM failure → raise OutreachGenerationError (caller decides to skip or retry)
"""

from app.schemas import EnrichedLead, EvaluatedLead, BusinessContext, OutreachOutput, ICPDecision
from app.core.exceptions import OutreachGenerationError
from app.core.logging import get_logger
from app.modules.outreach.generator import OutreachGenerator

logger = get_logger(__name__)


class OutreachService:
    def __init__(self) -> None:
        self._generator = OutreachGenerator()

    async def generate(
        self,
        enriched: EnrichedLead,
        evaluated: EvaluatedLead,
        context: BusinessContext,
    ) -> OutreachOutput | None:
        if evaluated.decision == ICPDecision.REJECTED:
            logger.info("outreach.skipped", lead_id=str(evaluated.lead_id), reason="icp_rejected")
            return None

        logger.info("outreach.generate.start", lead_id=str(evaluated.lead_id), decision=evaluated.decision.value)

        try:
            output = await self._generator.draft(enriched, evaluated, context)
            logger.info(
                "outreach.generate.done",
                lead_id=str(evaluated.lead_id),
                language=output.language.value,
                word_count=output.word_count,
            )
            return output
        except Exception as e:
            raise OutreachGenerationError(
                f"Failed to generate outreach for {evaluated.lead_id}: {e}"
            ) from e
