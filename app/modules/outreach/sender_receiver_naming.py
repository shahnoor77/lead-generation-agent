"""
Resolves how to address the prospect in outreach drafts.

Uses professional, hardcoded greetings — no auto-detection from email/names.
This avoids sending unprofessional things like "Dear Ascend," "Dear Therapeutic," etc.
"""

from __future__ import annotations
from dataclasses import dataclass
from app.schemas import EnrichedLead


@dataclass(frozen=True)
class ReceiverOutreachPlan:
    """How to open the email."""
    opener_for_fallback: str  # e.g. "Hello," or "To Whom It May Concern,"
    opening_instruction: str  # instruction for the LLM prompt


def plan_receiver_outreach(enriched: EnrichedLead, company_name: str) -> ReceiverOutreachPlan:
    """
    Returns a professional greeting based on available contact info.
    Uses key_people[0] as the contact name if available.
    """
    # Try to extract a name from key_people
    contact_name: str | None = None
    if enriched.key_people:
        raw = enriched.key_people[0].strip()
        # key_people entries may be "Name - Title" or just "Name"
        contact_name = raw.split(" - ")[0].split(" — ")[0].strip() or None

    if contact_name:
        name_parts = contact_name.split()
        first_name = name_parts[0] if name_parts else contact_name
        opener = f"Dear {first_name},"
        instr = (
            f"Opening line: Use exactly this greeting: \"{opener}\"\n"
            f"Do not change or paraphrase it."
        )
        return ReceiverOutreachPlan(
            opener_for_fallback=opener,
            opening_instruction=instr,
        )

    # No contact name — use company or generic
    if company_name and company_name.strip():
        opener = f"Dear {company_name} Team,"
        instr = (
            f"Opening line: Use exactly this greeting: \"{opener}\"\n"
            f"Address the prospect as a team member of {company_name}.\n"
            f"Do not change or paraphrase it."
        )
    else:
        opener = "To Whom It May Concern,"
        instr = (
            f"Opening line: Use exactly this greeting: \"{opener}\"\n"
            f"This is a formal, professional opening when no contact name is available.\n"
            f"Do not change or paraphrase it."
        )

    return ReceiverOutreachPlan(
        opener_for_fallback=opener,
        opening_instruction=instr,
    )


async def load_sender_signoff_name(user_id: str | None) -> str:
    """
    Name to print after Best regards / Sincerely.
    Priority: active sender account display_name → fallback.
    """
    if user_id is None:
        return "Our Team"

    from sqlmodel import select
    from app.storage.database import AsyncSessionLocal
    from app.storage.models import SenderEmailAccountRecord

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == user_id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1),
        )
        acc = result.scalar_one_or_none()

    if acc and acc.display_name and acc.display_name.strip():
        return acc.display_name.strip()

    return "Our Team"
