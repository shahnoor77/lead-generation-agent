"""
LLM-based ICP scorer — adds nuanced reasoning on top of rule results.
Uses Ollama (local) via the OpenAI-compatible /v1 endpoint.
Model: qwen2.5-coder:14b — strong at structured JSON output.
Only called when rule_score >= 45 (enforced by ICPEvaluationService).
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnrichedLead, BusinessContext, ICPRuleResult
from app.utils.prompt_loader import load_prompt

logger = get_logger(__name__)

client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=120.0,
)


@dataclass
class LLMScorerResult:
    score: int          # 0–100
    confidence: float   # 0.0–1.0
    reasoning: str


class LLMScorer:
    async def score(
        self,
        lead: EnrichedLead,
        context: BusinessContext,
        rule_results: list[ICPRuleResult],
    ) -> LLMScorerResult:
        prompt = load_prompt("icp_score").format(
            company_name=lead.company_name,
            website_summary=lead.summary or "N/A",
            services=", ".join(lead.services_detected) or "N/A",
            industries=", ".join(context.industries),
            domain=context.domain or "N/A",
            location=context.location,
            pain_points=", ".join(context.pain_points) if context.pain_points else "N/A",
            value_proposition=context.value_proposition or "N/A",
            notes=context.notes or "N/A",
            rule_summary=self._format_rules(rule_results),
        )

        response = await client.chat.completions.create(
            model=settings.ollama_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a JSON-only responder. Output valid JSON and nothing else.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.1,
        )

        raw = response.choices[0].message.content or "{}"
        # Strip any markdown fences Ollama may add
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("icp.llm_scorer.json_parse_failed", raw=raw[:200])
            data = {}

        return LLMScorerResult(
            score=self._parse_score(data.get("score")),
            confidence=self._parse_confidence(data.get("confidence")),
            reasoning=str(data.get("reasoning", "")) or "",
        )

    def _parse_score(self, value: object) -> int:
        """
        Safely coerce score to int 0–100.
        Handles: int, float, numeric string, legacy string labels.
        Falls back to 50 on any failure.
        """
        _LABEL_MAP = {"high": 80, "medium": 55, "low": 20}
        if value is None:
            return 50
        if isinstance(value, str):
            v = value.strip().lower()
            if v in _LABEL_MAP:
                logger.warning("icp.llm_scorer.string_score_received", value=v)
                return _LABEL_MAP[v]
            try:
                return max(0, min(100, round(float(v))))
            except (ValueError, TypeError):
                logger.warning("icp.llm_scorer.unparseable_score", value=repr(value))
                return 50
        try:
            return max(0, min(100, round(float(value))))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            logger.warning("icp.llm_scorer.unparseable_score", value=repr(value))
            return 50

    def _parse_confidence(self, value: object) -> float:
        """Safely coerce confidence to float 0.0–1.0. Falls back to 0.5."""
        if value is None:
            return 0.5
        try:
            return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (ValueError, TypeError):
            logger.warning("icp.llm_scorer.unparseable_confidence", value=repr(value))
            return 0.5

    def _format_rules(self, rules: list[ICPRuleResult]) -> str:
        return "\n".join(
            f"- {r.rule_name}: {'PASS' if r.passed else 'FAIL'} — {r.reason}"
            for r in rules
        )
