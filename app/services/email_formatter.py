"""
Email formatting service — generates formal, personalized outreach emails.
Applies industry and company-specific tone, greeting formality, and content structure.
"""

from __future__ import annotations
import json
from enum import Enum
from app.core.logging import get_logger
from app.schemas import EnrichedLead, BusinessContext
from app.utils.llm_client import llm_chat
from app.utils.prompt_loader import load_prompt
from app.core.config import settings

logger = get_logger(__name__)


class EmailTone(str, Enum):
    """Email tone/formality levels."""
    FORMAL = "formal"
    PROFESSIONAL = "professional"
    CONSULTATIVE = "consultative"
    FRIENDLY = "friendly"


class EmailFormatter:
    """Generates industry-specific, personalized outreach emails."""

    # Greeting templates by tone and role
    _GREETING_TEMPLATES: dict[EmailTone, dict[str, str]] = {
        EmailTone.FORMAL: {
            "default": "Dear {contact_title}{contact_last_name},",
            "generic": "Dear {company_name} Team,",
            "manager": "Dear {company_name} Management Team,",
            "director": "Dear {contact_title} {contact_last_name},",
            "executive": "Dear {contact_title},",
        },
        EmailTone.PROFESSIONAL: {
            "default": "Hi {contact_first_name},",
            "generic": "Hello {company_name} Team,",
            "manager": "Hi {contact_title} {contact_last_name},",
            "director": "Hello {contact_title} {contact_last_name},",
            "executive": "Hi {contact_title},",
        },
        EmailTone.CONSULTATIVE: {
            "default": "Hello {contact_first_name},",
            "generic": "Hi {company_name} Team,",
            "manager": "Hello {contact_first_name},",
            "director": "Hi {contact_title} {contact_last_name},",
            "executive": "Hello {contact_title},",
        },
        EmailTone.FRIENDLY: {
            "default": "Hi {contact_first_name},",
            "generic": "Hi {company_name} Team,",
            "manager": "Hi {contact_first_name},",
            "director": "Hi {contact_first_name},",
            "executive": "Hi {contact_first_name},",
        },
    }

    # Closing templates by tone
    _CLOSING_TEMPLATES: dict[EmailTone, str] = {
        EmailTone.FORMAL: "Best regards,\n{sender_name}\n{sender_title}\n{sender_company}",
        EmailTone.PROFESSIONAL: "Best regards,\n{sender_name}\n{sender_title}\n{sender_company}",
        EmailTone.CONSULTATIVE: "Looking forward to connecting,\n{sender_name}\n{sender_title}\n{sender_company}",
        EmailTone.FRIENDLY: "Talk soon,\n{sender_name}\n{sender_title}\n{sender_company}",
    }

    @staticmethod
    def _determine_contact_role(enriched: EnrichedLead) -> str:
        """Infer contact role from available data."""
        if not enriched.contact_title:
            return "default"

        title_lower = enriched.contact_title.lower()
        if any(x in title_lower for x in ["ceo", "founder", "president", "vp", "chief"]):
            return "executive"
        elif any(x in title_lower for x in ["director", "head of", "lead"]):
            return "director"
        elif any(x in title_lower for x in ["manager", "supervisor"]):
            return "manager"
        return "default"

    @staticmethod
    def _format_greeting(
        enriched: EnrichedLead,
        tone: EmailTone,
    ) -> str:
        """Generate formal, personalized greeting."""
        role = EmailFormatter._determine_contact_role(enriched)
        template = EmailFormatter._GREETING_TEMPLATES[tone].get(role, EmailFormatter._GREETING_TEMPLATES[tone]["default"])

        params = {
            "contact_first_name": enriched.contact_first_name or "there",
            "contact_last_name": enriched.contact_last_name or "",
            "contact_title": enriched.contact_title or "",
            "company_name": enriched.company_name,
        }

        # Clean up title with proper formatting
        if params["contact_title"]:
            params["contact_title"] = params["contact_title"].strip() + " "

        return template.format(**params).strip()

    @staticmethod
    def _format_closing(
        tone: EmailTone,
        sender_name: str = "Your Name",
        sender_title: str = "Account Executive",
        sender_company: str = "Your Company",
    ) -> str:
        """Generate formal closing."""
        template = EmailFormatter._CLOSING_TEMPLATES[tone]
        return template.format(
            sender_name=sender_name,
            sender_title=sender_title,
            sender_company=sender_company,
        )

    @staticmethod
    async def generate_email(
        enriched: EnrichedLead,
        context: BusinessContext,
        tone: EmailTone = EmailTone.PROFESSIONAL,
        *,
        pain_points: list[str] | None = None,
        sender_name: str = "Our Team",
        sender_title: str = "Account Executive",
        sender_company: str = "Your Company",
    ) -> dict:
        """
        Generate a complete, personalized outreach email.

        Returns dict with:
          - greeting: str (formal, personalized)
          - subject: str (industry/company-specific)
          - body: str (full email body, industry-aware)
          - closing: str (formal closing)
          - tone: str (tone used)
          - word_count: int
        """
        if pain_points is None:
            pain_points = context.pain_points or []

        try:
            prompt = load_prompt("email_generation").format(
                company_name=enriched.company_name,
                industry=enriched.industry or ", ".join(context.industries),
                domain=context.domain or "N/A",
                company_summary=enriched.summary or "N/A",
                services=", ".join(enriched.services_detected) if enriched.services_detected else "N/A",
                pain_points="\n".join(f"- {p}" for p in pain_points) if pain_points else "N/A",
                contact_name=f"{enriched.contact_first_name} {enriched.contact_last_name}".strip() or "Hiring Manager",
                contact_title=enriched.contact_title or "N/A",
                tone_name=tone.value,
                our_value_prop=context.value_proposition or "We help improve operational efficiency",
                target_audience=context.target_audience or "decision makers",
            )

            response = await llm_chat(
                model=settings.ollama_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert B2B outreach email copywriter. Output valid JSON and nothing else.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.4,
            )

            raw = response.choices[0].message.content or "{}"
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)

            subject = data.get("subject", f"Helping {enriched.company_name} with {pain_points[0] if pain_points else 'growth'}")
            body = data.get("body", "")

            greeting = EmailFormatter._format_greeting(enriched, tone)
            closing = EmailFormatter._format_closing(tone, sender_name, sender_title, sender_company)

            full_email = f"{greeting}\n\n{body}\n\n{closing}"
            word_count = len(full_email.split())

            logger.info(
                "email_generation.success",
                lead_id=str(enriched.lead_id),
                subject_len=len(subject),
                word_count=word_count,
                tone=tone.value,
            )

            return {
                "greeting": greeting,
                "subject": subject,
                "body": body,
                "closing": closing,
                "full_email": full_email,
                "tone": tone.value,
                "word_count": word_count,
            }

        except Exception as e:
            logger.warning(
                "email_generation.failed",
                lead_id=str(enriched.lead_id),
                error=str(e),
            )
            # Return minimal fallback
            greeting = EmailFormatter._format_greeting(enriched, tone)
            closing = EmailFormatter._format_closing(tone, sender_name, sender_title, sender_company)
            return {
                "greeting": greeting,
                "subject": f"Helping {enriched.company_name} achieve its goals",
                "body": f"We work with companies like {enriched.company_name} to improve {context.domain or 'business operations'}.",
                "closing": closing,
                "full_email": f"{greeting}\n\nWe work with companies like {enriched.company_name} to improve {context.domain or 'business operations'}.\n\n{closing}",
                "tone": tone.value,
                "word_count": 0,
            }
