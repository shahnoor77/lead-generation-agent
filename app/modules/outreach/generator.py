"""
LLM-based outreach draft generator.
Uses Ollama (local) via the OpenAI-compatible /v1 endpoint.
Model: qwen2.5-coder:14b — reliable structured JSON output.
word_count is computed automatically by OutreachOutput (computed_field).

Pain points are inferred dynamically per company before drafting.
Language is resolved per-lead when context.language_preference == AUTO.
"""

from __future__ import annotations
import json
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnrichedLead, EvaluatedLead, BusinessContext, OutreachOutput, OutreachLanguage
from app.utils.prompt_loader import load_prompt
from app.modules.outreach.pain_inference import infer_pain_points

logger = get_logger(__name__)

client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=120.0,
)

# ── Language resolution ────────────────────────────────────────────────────────

def _resolve_language(context: BusinessContext, enriched: EnrichedLead) -> OutreachLanguage:
    """
    Resolve the actual language to use for this specific lead.

    AUTO logic (in priority order):
      1. Website is English-only  → EN
      2. Website is Arabic-only   → AR
      3. Website is bilingual     → AR  (Arabic preferred for KSA B2B)
      4. No website language data → AR  (safe default for KSA market)

    EN / AR preferences are returned as-is.
    """
    pref = context.language_preference

    if pref != OutreachLanguage.AUTO:
        return pref

    # AUTO → always English regardless of website language
    resolved = OutreachLanguage.EN

    logger.info(
        "outreach.language.resolved",
        lead_id=str(enriched.lead_id),
        resolved=resolved.value,
    )
    return resolved

    logger.info(
        "outreach.language.resolved",
        lead_id=str(enriched.lead_id),
        site_language=site_lang or "unknown",
        
        resolved=resolved.value,
    )
    return resolved


class OutreachGenerator:
    async def draft(
        self,
        enriched: EnrichedLead,
        evaluated: EvaluatedLead,
        context: BusinessContext,
    ) -> OutreachOutput:
        # ── Step 1: Resolve language for this specific lead ───────────────────
        resolved_language = _resolve_language(context, enriched)

        # ── Step 2: Infer pain points dynamically for this company ────────────
        inferred_pain_points = await infer_pain_points(enriched, evaluated, context)

        # ── Step 3: Build personalization hooks ───────────────────────────────
        personalization_hooks = self._build_hooks(enriched, evaluated)

        # ── Step 4: Generate outreach draft ───────────────────────────────────
        prompt = load_prompt("outreach_draft").format(
            company_name=evaluated.company_name,
            website_summary=enriched.summary or evaluated.llm_reasoning or "N/A",
            services=", ".join(enriched.services_detected) if enriched.services_detected else "N/A",
            key_people=", ".join(enriched.key_people) if enriched.key_people else "N/A",
            pain_points=", ".join(context.pain_points) if context.pain_points else "N/A",
            inferred_pain_points=self._format_pain_points(inferred_pain_points),
            value_proposition=context.value_proposition or "N/A",
            domain=context.domain or "N/A",
            notes=context.notes or "N/A",
            language=resolved_language.value,
            personalization_hooks="\n".join(f"- {h}" for h in personalization_hooks),
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
            max_tokens=500,
            temperature=0.4,
        )

        raw = response.choices[0].message.content or "{}"
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "outreach.generator.json_parse_failed",
                lead_id=str(evaluated.lead_id),
                raw=raw[:200],
            )
            data = {}

        return OutreachOutput(
            lead_id=evaluated.lead_id,
            trace_id=evaluated.trace_id,
            pipeline_run_id=evaluated.pipeline_run_id,
            email_subject=data.get("subject_line", "Draft subject")[:80],
            email_body=self._trim_to_words(data.get("message_body", "Draft body."), 220),
            language=resolved_language,
            personalization_hooks=personalization_hooks,
            max_allowed_words=250,
            approved=False,
        )

    def _build_hooks(self, enriched: EnrichedLead, evaluated: EvaluatedLead) -> list[str]:
        hooks: list[str] = []
        if enriched.summary:
            hooks.append(f"Summary: {enriched.summary[:120]}")
        if enriched.services_detected:
            hooks.append(f"Services: {', '.join(enriched.services_detected[:3])}")
        if enriched.key_people:
            hooks.append(f"Key contact: {enriched.key_people[0]}")
        if enriched.founding_year:
            hooks.append(f"Founded: {enriched.founding_year}")
        if evaluated.llm_reasoning:
            hooks.append(f"ICP signal: {evaluated.llm_reasoning[:100]}")
        if evaluated.website:
            hooks.append(f"Website: {evaluated.website}")
        return hooks

    def _format_pain_points(self, points: list[str]) -> str:
        if not points:
            return "N/A"
        return "\n".join(f"- {p}" for p in points)

    def _trim_to_words(self, text: str, max_words: int) -> str:
        """Trim text to at most max_words words, preserving sentence boundaries where possible."""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words])
