"""
ICP Evaluation Module
---------------------
Responsibility: Score enriched leads against Ideal Customer Profile.

Evaluation order:
  1. Rule engine (always, fast, deterministic)
  2. Buyer/Seller classification (always, rule-based + optional LLM tie-breaker)
     → SELLER penalty applied to rule_score before LLM gate
  3. LLM scorer (conditional — only if adjusted rule_score >= threshold)
  4. fit_score computed, decision made

Failure strategy:
- Rule engine never fails
- Buyer/seller classifier never fails (falls back to UNCERTAIN)
- LLM failure → rule-only score used, llm_was_called=False
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
from app.modules.qualification.buyer_seller_classifier import (
    classify_buyer_seller,
    apply_buyer_seller_penalty,
    BuyerSellerLabel,
    BuyerSellerResult,
)

logger = get_logger(__name__)

_RULE_SCORE_LLM_THRESHOLD = 45


class ICPEvaluationService:
    def __init__(self) -> None:
        self._rules = RuleEngine()
        self._llm = LLMScorer()

    async def evaluate(self, lead: EnrichedLead, context: BusinessContext) -> EvaluatedLead:
        logger.info("icp.evaluate.start", lead_id=str(lead.lead_id), trace_id=str(lead.trace_id))

        # ── Step 1: Rule engine ────────────────────────────────────────────────
        rule_results = self._rules.run(lead, context)
        passed = sum(1 for r in rule_results if r.passed)
        total = len(rule_results)
        rule_score = round((passed / total) * 100) if total else 0

        # ── Step 2: Buyer/Seller classification ───────────────────────────────
        # Always runs. LLM tie-breaker only for UNCERTAIN cases.
        bs_result: BuyerSellerResult | None = None
        penalty_reason: str | None = None
        try:
            bs_result = await classify_buyer_seller(lead, context)
            rule_score, penalty_reason = apply_buyer_seller_penalty(rule_score, bs_result)

            logger.info(
                "icp.buyer_seller",
                lead_id=str(lead.lead_id),
                classification=bs_result.classification.value,
                buyer_score=bs_result.buyer_score,
                seller_score=bs_result.seller_score,
                adjusted_rule_score=rule_score,
            )
        except Exception as e:
            logger.warning("icp.buyer_seller.failed", lead_id=str(lead.lead_id), error=str(e))

        # ── Step 3: LLM scorer (only if rule_score still above threshold) ─────
        llm_score: int | None = None
        llm_reasoning: str | None = None
        llm_was_called = False
        confidence = round(rule_score / 100, 2)

        if rule_score >= _RULE_SCORE_LLM_THRESHOLD:
            try:
                llm_result = await self._llm.score(lead, context, rule_results)
                llm_score = llm_result.score
                llm_reasoning = llm_result.reasoning
                confidence = llm_result.confidence
                llm_was_called = True
            except Exception as e:
                logger.warning("icp.llm_scorer.failed", lead_id=str(lead.lead_id), error=str(e))

        # ── Step 4: fit_score + decision ──────────────────────────────────────
        fit_score = (
            round((rule_score + llm_score) / 2)
            if llm_score is not None
            else rule_score
        )

        decision = ICPDecision.QUALIFIED if fit_score >= _RULE_SCORE_LLM_THRESHOLD else ICPDecision.REJECTED

        # Build disqualification reason — include buyer/seller info if relevant
        disq_reason: str | None = None
        if decision == ICPDecision.REJECTED:
            if penalty_reason:
                disq_reason = penalty_reason
            else:
                disq_reason = "rule_score_below_threshold"

        # Append buyer/seller classification to LLM reasoning for operator visibility
        bs_note = ""
        if bs_result:
            bs_note = (
                f" [Buyer/Seller: {bs_result.classification.value} "
                f"(buyer={bs_result.buyer_score}, seller={bs_result.seller_score})]"
            )

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
            llm_reasoning=(llm_reasoning or "") + bs_note if (llm_reasoning or bs_note) else None,
            disqualification_reason=disq_reason,
        )

        logger.info(
            "icp.evaluate.done",
            lead_id=str(lead.lead_id),
            fit_score=fit_score,
            rule_score=rule_score,
            llm_called=llm_was_called,
            decision=decision.value,
            buyer_seller=bs_result.classification.value if bs_result else "N/A",
        )
        return evaluated
