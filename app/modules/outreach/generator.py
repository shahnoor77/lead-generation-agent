"""
LLM-based outreach draft generator with output quality validation and retry logic.
Uses shared LLM client — handles Ollama server load gracefully.
"""

from __future__ import annotations
import json

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnrichedLead, EvaluatedLead, BusinessContext, OutreachOutput, OutreachLanguage
from app.utils.prompt_loader import load_prompt
from app.utils.llm_client import llm_chat
from app.modules.outreach.pain_inference import infer_pain_points
from app.modules.quality.output_quality_validator import (
    validate_outreach,
    outreach_fallback,
)

logger = get_logger(__name__)

_FALLBACK_SUBJECT_PREFIX = "[DRAFT NEEDED] "


def _resolve_language(context: BusinessContext, enriched: EnrichedLead) -> OutreachLanguage:
    pref = context.language_preference
    if pref != OutreachLanguage.AUTO:
        return pref
    # AUTO → always English
    return OutreachLanguage.EN


class OutreachGenerator:
    async def draft(
        self,
        enriched: EnrichedLead,
        evaluated: EvaluatedLead,
        context: BusinessContext,
    ) -> OutreachOutput:
        resolved_language = _resolve_language(context, enriched)
        inferred_pain_points = await infer_pain_points(enriched, evaluated, context)
        personalization_hooks = self._build_hooks(enriched, evaluated)

        prompt = load_prompt("outreach_draft").format(
            company_name=evaluated.company_name,
            website_summary=enriched.summary or evaluated.llm_reasoning or "N/A",
            services=", ".join(enriched.services_detected) if enriched.services_detected else "N/A",
            key_people=", ".join(enriched.key_people) if enriched.key_people else "N/A",
            pain_points=", ".join(context.pain_points) if context.pain_points else "N/A",
            inferred_pain_points=self._format_pain_points(inferred_pain_points),
            our_services=", ".join(context.our_services) if context.our_services else "N/A",
            value_proposition=context.value_proposition or "N/A",
            domain=context.domain or "N/A",
            notes=context.notes or "N/A",
            language=resolved_language.value,
            personalization_hooks="\n".join(f"- {h}" for h in personalization_hooks),
        )

        subject: str = ""
        body: str = ""
        is_fallback = False

        try:
            response = await llm_chat(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": "You are a JSON-only responder. Output valid JSON and nothing else."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.4,
            )
            raw = response.choices[0].message.content or "{}"
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            try:
                data = json.loads(raw)
                subject = str(data.get("subject_line", "")).strip()[:80]
                body = self._trim_to_words(str(data.get("message_body", "")).strip(), 220)
            except json.JSONDecodeError:
                logger.warning(
                    "outreach.json_parse_failed",
                    lead_id=str(evaluated.lead_id),
                    raw=raw[:200],
                )
                is_fallback = True

        except Exception as e:
            logger.warning("outreach.llm_failed", lead_id=str(evaluated.lead_id), error=str(e))
            is_fallback = True

        # Validate quality if LLM produced output
        if not is_fallback and subject and body:
            result = validate_outreach(subject, body, evaluated.company_name)
            if not result.passed:
                logger.warning(
                    "outreach.quality_failed",
                    lead_id=str(evaluated.lead_id),
                    issues=result.issues,
                )
                is_fallback = True

        # Apply fallback if needed
        if is_fallback or not subject or not body:
            subject, body = outreach_fallback(evaluated.company_name)
            subject = _FALLBACK_SUBJECT_PREFIX + subject
            logger.info("outreach.fallback_used", lead_id=str(evaluated.lead_id))

        return OutreachOutput(
            lead_id=evaluated.lead_id,
            trace_id=evaluated.trace_id,
            pipeline_run_id=evaluated.pipeline_run_id,
            email_subject=subject[:80],
            email_body=body[:2000],
            language=resolved_language,
            personalization_hooks=personalization_hooks,
            max_allowed_words=300,
            approved=False,
        )

    def _build_hooks(self, enriched: EnrichedLead, evaluated: EvaluatedLead) -> list[str]:
        hooks: list[str] = []
        if enriched.summary and "[auto-fallback]" not in enriched.summary:
            hooks.append(f"Summary: {enriched.summary[:120]}")
        if enriched.services_detected:
            hooks.append(f"Services: {', '.join(enriched.services_detected[:3])}")
        if enriched.key_people:
            hooks.append(f"Key contact: {enriched.key_people[0]}")
        if enriched.founding_year:
            hooks.append(f"Founded: {enriched.founding_year}")
        if evaluated.llm_reasoning:
            clean = evaluated.llm_reasoning.split("[Buyer/Seller:")[0].strip()
            if clean:
                hooks.append(f"ICP signal: {clean[:100]}")
        if evaluated.website:
            hooks.append(f"Website: {evaluated.website}")
        return hooks

    def _format_pain_points(self, points: list[str]) -> str:
        return "\n".join(f"- {p}" for p in points) if points else "N/A"

    def _trim_to_words(self, text: str, max_words: int) -> str:
        words = text.split()
        return text if len(words) <= max_words else " ".join(words[:max_words])
