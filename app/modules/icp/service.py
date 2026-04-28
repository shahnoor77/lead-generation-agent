"""
ICP Evaluation Module
---------------------
Responsibility: Score enriched leads against Ideal Customer Profile.
Strategy: Rules-first (fast, deterministic) → LLM reasoning (conditional).
Input:  EnrichedLead + BusinessContext
Output: EvaluatedLead

LLM gate: only called when rule_score >= 45. Never called for low-scoring leads.

Failure strategy:
- Rule engine never fails (pure Python logic)
- LLM failure → fall back to rule-only score, log warning, llm_was_called=False
"""

from datetime import datetime, timezone

from app.schemas import (
    BusinessContext,
    EnrichedLead,
    EvaluatedLead,
    ICPDecision,
    ICPRuleResult,
)
from app.core.logging import get_logger
from app.modules.icp.rules import RuleEngine
from app.modules.icp.llm_scorer import LLMScorer

logger = get_logger(__name__)

_RULE_SCORE_LLM_THRESHOLD = 45  # LLM not called below this


class ICPEvaluationService:
    def __init__(self) -> None:
        self._rules = RuleEngine()
        self._llm = LLMScorer()

    async def evaluate(self, lead: EnrichedLead, context: BusinessContext) -> EvaluatedLead:
        logger.info("icp.evaluate.start", lead_id=str(lead.lead_id), trace_id=str(lead.trace_id))

        rule_results = self._rules.run(lead, context)
        passed = sum(1 for r in rule_results if r.passed)
        total = len(rule_results)
        rule_score = round((passed / total) * 100) if total else 0

        llm_score: int | None = None
        llm_reasoning: str | None = None
        llm_was_called = False
        confidence = round(rule_score / 100, 2)

        # LLM only called when rule_score is above threshold
        if rule_score >= _RULE_SCORE_LLM_THRESHOLD:
            try:
                llm_result = await self._llm.score(lead, context, rule_results)
                llm_score = llm_result.score
                llm_reasoning = llm_result.reasoning
                confidence = llm_result.confidence
                llm_was_called = True
            except Exception as e:
                logger.warning("icp.llm_scorer.failed", lead_id=str(lead.lead_id), error=str(e))

        # fit_score: average of rule + llm if available, else rule only
        fit_score = (
            round((rule_score + llm_score) / 2)
            if llm_score is not None
            else rule_score
        )

        decision = ICPDecision.QUALIFIED if fit_score >= _RULE_SCORE_LLM_THRESHOLD else ICPDecision.REJECTED

        evaluated = EvaluatedLead(
            lead_id=lead.lead_id,
            trace_id=lead.trace_id,
            pipeline_run_id=lead.pipeline_run_id,
            company_name=lead.company_name,
            location=lead.location,
            website=lead.website,
            fit_score=fit_score,
            rule_score=rule_score,
            llm_score=llm_score,
            llm_was_called=llm_was_called,
            confidence_score=confidence,
            decision=decision,
            rule_results=rule_results,
            llm_reasoning=llm_reasoning,
            disqualification_reason=(
                "rule_score_below_threshold" if decision == ICPDecision.REJECTED else None
            ),
        )

        logger.info(
            "icp.evaluate.done",
            lead_id=str(lead.lead_id),
            fit_score=fit_score,
            rule_score=rule_score,
            llm_called=llm_was_called,
            decision=decision.value,
        )
        return evaluated
