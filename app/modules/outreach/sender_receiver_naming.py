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
    
    Priority:
    1. If contact_name + contact_title both present → "Dear {Title} {LastName},"
    2. If contact_name only → "Dear {FirstName},"
    3. Otherwise → "Dear {Company} Team," or "To Whom It May Concern,"
    
    NO auto-detection from email local parts or unreliable signals.
    """
    
    # Case 1: Full contact name + title
    if enriched.contact_name and enriched.contact_title:
        # Extract last name (last word of contact_name)
        name_parts = enriched.contact_name.strip().split()
        last_name = name_parts[-1] if name_parts else enriched.contact_name
        title = enriched.contact_title.strip()
        
        opener = f"Dear {title} {last_name},"
        instr = (
            f"Opening line: Use exactly this greeting: \"{opener}\"\n"
            f"Do not change or paraphrase it."
        )
        return ReceiverOutreachPlan(
            opener_for_fallback=opener,
            opening_instruction=instr,
        )
    
    # Case 2: Contact name only (no title)
    if enriched.contact_name:
        name_parts = enriched.contact_name.strip().split()
        first_name = name_parts[0] if name_parts else enriched.contact_name
        
        opener = f"Dear {first_name},"
        instr = (
            f"Opening line: Use exactly this greeting: \"{opener}\"\n"
            f"Do not change or paraphrase it."
        )
        return ReceiverOutreachPlan(
            opener_for_fallback=opener,
            opening_instruction=instr,
        )
    
    # Case 3: No contact name — use company or generic
    # Prefer company team over "To Whom It May Concern"
    if company_name and company_name.strip():
        opener = f"Dear {company_name} Team,"
        instr = (
            f"Opening line: Use exactly this greeting: \"{opener}\"\n"
            f"Address the prospect as a team member of {company_name}.\n"
            f"Do not change or paraphrase it."
        )
    else:
        # Fallback if even company_name is missing
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
