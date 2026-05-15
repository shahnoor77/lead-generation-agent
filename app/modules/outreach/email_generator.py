"""
Enhanced email generation for outreach.
Integrates formal greeting formatting and industry-specific personalization.
"""

from __future__ import annotations
from app.schemas import EnrichedLead, BusinessContext, EvaluatedLead
from app.services.email_formatter import EmailFormatter, EmailTone
from app.core.logging import get_logger

logger = get_logger(__name__)


async def generate_outreach_email(
    enriched: EnrichedLead,
    evaluated: EvaluatedLead,
    context: BusinessContext,
    pain_points: list[str] | None = None,
    tone: str = "professional",
) -> dict:
    """
    Generate a complete outreach email with formal greeting and personalization.

    Args:
        enriched: Enriched lead data
        evaluated: ICP evaluation result
        context: Business context (industry, domain, value prop)
        pain_points: Inferred pain points (3-5 strings)
        tone: "formal", "professional", "consultative", or "friendly"

    Returns dict with:
        - greeting, subject, body, closing, full_email, tone, word_count
    """
    try:
        tone_enum = EmailTone(tone.lower())
    except ValueError:
        logger.warning("email_generator.invalid_tone", tone=tone, defaulting_to="professional")
        tone_enum = EmailTone.PROFESSIONAL

    email_dict = await EmailFormatter.generate_email(
        enriched=enriched,
        context=context,
        tone=tone_enum,
        pain_points=pain_points or [],
        sender_name="Your Sales Team",
        sender_title="Account Executive",
        sender_company=context.company_name or "Your Company",
    )

    logger.info(
        "email_generator.complete",
        lead_id=str(enriched.lead_id),
        company=enriched.company_name,
        word_count=email_dict.get("word_count", 0),
        tone=tone,
    )

    return email_dict
