"""
Outreach Draft Generator — tone-aware, name-aware, domain-aware, auto-subject.

- Receiver greeting: real first name when verified; otherwise neutral / team @ company (no bogus "Dear Intermediate,")
- Sender sign-off: user's saved sender display name or settings sender domain / account email
- Industry context in subject; tone from AI agent settings
"""

from __future__ import annotations
import json
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.schemas import EnrichedLead, EvaluatedLead, BusinessContext, OutreachOutput, OutreachLanguage
from app.utils.prompt_loader import load_prompt
from app.utils.llm_client import llm_chat
from app.modules.outreach.pain_inference import infer_pain_points
from app.modules.quality.output_quality_validator import validate_outreach, outreach_fallback
from app.modules.outreach.email_sanitize import clean_outreach_copy
from app.modules.outreach.sender_receiver_naming import (
    load_sender_signoff_name,
    plan_receiver_outreach,
)

logger = get_logger(__name__)

_TONE_INSTRUCTIONS: dict[str, str] = {
    "executive-direct": (
        "Write in a direct, executive-to-executive tone. "
        "No fluff. Lead with business impact. Short sentences. "
        "Assume the reader is a busy C-level executive."
    ),
    "formal-business": (
        "Write in a professional, human, formal business tone. "
        "Use clear, respectful language suitable for senior decision-makers. "
        "Avoid sales jargon and keep transitions natural."
    ),
    "problem-specific": (
        "Write in a consultative, problem-focused tone. "
        "Lead with an industry challenge observation. "
        "Position as a knowledgeable peer, not a salesperson."
    ),
}


def _extract_receiver_domain(enriched: EnrichedLead) -> str:
    """Extract company domain from contact email or website URL."""
    if enriched.contact_email:
        parts = str(enriched.contact_email).split("@")
        if len(parts) == 2:
            return parts[1].lower()
    if enriched.website:
        try:
            parsed = urlparse(str(enriched.website))
            domain = parsed.netloc.lower().removeprefix("www.")
            return domain
        except Exception:
            pass
    return ""


def _resolve_language(context: BusinessContext, enriched: EnrichedLead) -> OutreachLanguage:
    pref = context.language_preference
    if pref != OutreachLanguage.AUTO:
        return pref
    return OutreachLanguage.EN


class OutreachGenerator:
    async def draft(
        self,
        enriched: EnrichedLead,
        evaluated: EvaluatedLead,
        context: BusinessContext,
        user_id: int | None = None,
        autonomous: bool = False,
    ) -> OutreachOutput:
        resolved_language = _resolve_language(context, enriched)
        inferred_pain_points = await infer_pain_points(enriched, evaluated, context)
        personalization_hooks = self._build_hooks(enriched, evaluated)

        # Autonomous mode: use problem-specific tone + lower temperature for precision
        tone_instruction = _TONE_INSTRUCTIONS["formal-business"]
        if autonomous:
            tone_instruction = _TONE_INSTRUCTIONS["problem-specific"]
        elif user_id is not None:
            try:
                from app.services.settings import get_settings
                user_settings = await get_settings(user_id)
                tone_key = user_settings.ai_agent.email_tone
                tone_instruction = _TONE_INSTRUCTIONS.get(tone_key, tone_instruction)
            except Exception:
                pass

        recv_plan = plan_receiver_outreach(enriched, evaluated.company_name)
        sender_signoff_name = await load_sender_signoff_name(user_id)
        receiver_domain = _extract_receiver_domain(enriched)
        industry = enriched.industry or (context.industries[0] if context.industries else "")

        prompt = load_prompt("outreach_draft").format(
            company_name=evaluated.company_name,
            receiver_opening_instruction=recv_plan.opening_instruction,
            receiver_first_name_hint=recv_plan.first_name_hint or "—",
            sender_signoff_name=sender_signoff_name,
            receiver_domain=receiver_domain or "N/A",
            industry=industry,
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
            tone_instruction=tone_instruction,
            personalization_hooks="\n".join(f"- {h}" for h in personalization_hooks),
        )

        # Autonomous: lower temperature + more retries for higher quality
        temperature = 0.2 if autonomous else 0.4
        max_tokens = 700 if autonomous else 600

        subject: str = ""
        body: str = ""
        is_fallback = False

        try:
            response = await llm_chat(
                messages=[
                    {"role": "system", "content": "You are a JSON-only responder. Output valid JSON and nothing else."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                user_id=user_id,
            )
            raw = (response.choices[0].message.content or "{}").strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            try:
                data = json.loads(raw)
                subject = str(data.get("subject_line", "")).strip()[:80]
                body = self._trim_to_words(str(data.get("message_body", "")).strip(), 250)
                subject, body = clean_outreach_copy(subject, body, for_send=False)
            except json.JSONDecodeError:
                logger.warning("outreach.json_parse_failed", lead_id=str(evaluated.lead_id), raw=raw[:200])
                is_fallback = True

        except Exception as e:
            logger.warning("outreach.llm_failed", lead_id=str(evaluated.lead_id), error=str(e))
            is_fallback = True

        if not is_fallback and subject and body:
            result = validate_outreach(subject, body, evaluated.company_name)
            if not result.passed:
                if autonomous:
                    # In autonomous mode, retry once with a stricter system prompt
                    logger.warning("outreach.quality_failed_autonomous_retry",
                                   lead_id=str(evaluated.lead_id), issues=result.issues)
                    subject, body = await self._retry_autonomous(prompt, evaluated.company_name)
                    if subject and body:
                        retry_check = validate_outreach(subject, body, evaluated.company_name)
                        is_fallback = not retry_check.passed
                    else:
                        is_fallback = True
                else:
                    logger.warning("outreach.quality_failed", lead_id=str(evaluated.lead_id), issues=result.issues)
                    is_fallback = True

        if is_fallback or not subject or not body:
            subject, body = outreach_fallback(
                evaluated.company_name,
                industry_hint=industry or None,
                receiver_opener=recv_plan.opener_for_fallback,
                sender_signoff_name=sender_signoff_name,
            )
            subject, body = clean_outreach_copy(subject, body, for_send=False)
            logger.info("outreach.fallback_used", lead_id=str(evaluated.lead_id), autonomous=autonomous)

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

    async def _retry_autonomous(self, original_prompt: str, company_name: str) -> tuple[str, str]:
        """One retry with stricter instructions for autonomous mode."""
        try:
            response = await llm_chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a JSON-only responder. Output ONLY valid JSON. "
                            "The email must be professional, specific, and under 180 words. "
                            "No generic phrases, no filler, no internal words (draft/pending review/AI). "
                            "Subject must reference the company's industry or operations. "
                            "First line must use a concrete detail from the user prompt's hooks."
                        ),
                    },
                    {"role": "user", "content": original_prompt},
                ],
                max_tokens=700,
                temperature=0.1,
            )
            raw = (response.choices[0].message.content or "{}").strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            subject = str(data.get("subject_line", "")).strip()[:80]
            body = self._trim_to_words(str(data.get("message_body", "")).strip(), 250)
            return clean_outreach_copy(subject, body, for_send=False)
        except Exception:
            return "", ""

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
