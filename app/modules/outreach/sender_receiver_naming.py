"""
Resolves how to address the prospect and sign off as the sender in outreach drafts.

Avoids treating role words, mailbox aliases (info@, intermediate@), or company
segments as a person's first name. Sign-off prefers the user's configured sender
display name from Settings / sender email account.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import EnrichedLead

# Email local parts / scraped tokens that must never be used as "Dear <name>,"
_MAILBOX_ALIAS_FIRST_TOKENS = frozenset(
    {
        "info",
        "contact",
        "sales",
        "support",
        "hello",
        "team",
        "admin",
        "office",
        "enquiries",
        "enquiry",
        "mail",
        "webmaster",
        "web",
        "noreply",
        "no",
        "reply",
        "help",
        "service",
        "services",
        "customerservice",
        "customer",
        "booking",
        "bookings",
        "reservation",
        "reservations",
        "orders",
        "hr",
        "careers",
        "jobs",
        "marketing",
        "newsletter",
        "general",
        "inquiries",
        "inquiry",
        "billing",
        "accounts",
        "reception",
        "main",
        "hq",
        "global",
        "usa",
        "uk",
        "me",
        "us",
        "hello",
    }
)

# Single tokens that read like tier/category/business words, not given names
_BUSINESS_OR_TIER_WORDS = frozenset(
    {
        "intermediate",
        "primary",
        "advanced",
        "basic",
        "standard",
        "premium",
        "executive",
        "commercial",
        "corporate",
        "group",
        "company",
        "business",
        "operations",
        "op",
        "the",
        "team",
        "management",
        "owner",
        "owners",
    }
)


@dataclass(frozen=True)
class ReceiverOutreachPlan:
    """How to open the email and what to tell the model."""

    opener_for_fallback: str  # first line only, e.g. "Hello," or "Maria,"
    opening_instruction: str  # full paragraph for the prompt
    uses_personal_first_name: bool
    first_name_hint: str = ""  # verified given name only, for prompt context line; else ""


def _clean_key_person_line(text: str) -> str:
    """Strip simple role prefixes from key_people lines."""
    t = text.strip()
    t = re.sub(
        r"^(owner|manager|director|ceo|coo|cfo|cto|cmo|gm|md|president|founder|partner|proprietor)\s*[:-–—]\s*",
        "",
        t,
        flags=re.IGNORECASE,
    )
    return t.strip()


def _first_alpha_token_from_name(full_name: str) -> str:
    """Use extract-style first token; reject obvious garbage."""
    if not full_name or not full_name.strip():
        return ""
    cleaned = re.sub(
        r"^(Mr\.?|Mrs\.?|Ms\.?|Miss\.?|Dr\.?|Eng\.?|Prof\.?)\s+",
        "",
        full_name.strip(),
        flags=re.IGNORECASE,
    )
    parts = cleaned.split()
    if not parts:
        return ""
    return parts[0]


def _is_plausible_given_name(token: str) -> bool:
    t = token.strip()
    if len(t) < 2 or len(t) > 40:
        return False
    tl = t.lower()
    if tl in _MAILBOX_ALIAS_FIRST_TOKENS or tl in _BUSINESS_OR_TIER_WORDS:
        return False
    if not any(c.isalpha() for c in t):
        return False
    return True


def _safe_name_from_key_people(key_people: list[str] | None) -> str | None:
    if not key_people:
        return None
    line = _clean_key_person_line(key_people[0])
    if not line:
        return None
    first = _first_alpha_token_from_name(line)
    if not first:
        return None
    if not _is_plausible_given_name(first):
        return None
    return first[:1].upper() + first[1:].lower() if len(first) > 1 else first


def _safe_name_from_email_local(contact_email: str | None) -> str | None:
    if not contact_email or "@" not in contact_email:
        return None
    local = contact_email.split("@")[0].lower()
    first_token = re.split(r"[._\-+]", local)[0]
    if not first_token or first_token in _MAILBOX_ALIAS_FIRST_TOKENS:
        return None
    if first_token in _BUSINESS_OR_TIER_WORDS:
        return None
    if not _is_plausible_given_name(first_token):
        return None
    return first_token[:1].upper() + first_token[1:].lower()


def plan_receiver_outreach(enriched: EnrichedLead, company_name: str) -> ReceiverOutreachPlan:
    """
    Prefer a real person first name from key_people, then a plausible email-local name.
    Otherwise use a neutral or team-wide opening — never a bogus \"Dear <tier>,\".
    """
    from_key = _safe_name_from_key_people(enriched.key_people if enriched.key_people else None)
    if from_key:
        instr = (
            f"Opening line: use only the prospect's first name followed by a comma, e.g. \"{from_key},\" — "
            "not \"Dear {name},\". Do not address them by company name or role as if it were their first name."
        )
        return ReceiverOutreachPlan(
            opener_for_fallback=f"{from_key},",
            opening_instruction=instr,
            uses_personal_first_name=True,
            first_name_hint=from_key,
        )

    from_email = _safe_name_from_email_local(
        str(enriched.contact_email) if enriched.contact_email else None
    )
    if from_email:
        instr = (
            f"Opening line: use only the inferred first name \"{from_email},\" followed by a comma (not \"Dear ...\"). "
            "If that feels wrong for the role, switch to a neutral opening instead (see fallback below)."
        )
        return ReceiverOutreachPlan(
            opener_for_fallback=f"{from_email},",
            opening_instruction=instr,
            uses_personal_first_name=True,
            first_name_hint=from_email,
        )

    cn = company_name.strip() or "your organization"
    instr = (
        "No reliable individual first name is known — do NOT invent one from the email local part or company words. "
        f"Open with a neutral line (e.g. \"Hello,\" or \"Good day,\") and in the next sentence acknowledge {cn} "
        "(e.g. leadership, the team, or whoever handles operations there — match any role hint in key people if present). "
        f'Never write \"Dear Intermediate,\" \"Dear {cn},\" as a person\'s name, or similar.'
    )
    return ReceiverOutreachPlan(
        opener_for_fallback="Hello,",
        opening_instruction=instr,
        uses_personal_first_name=False,
        first_name_hint="",
    )


async def load_sender_signoff_name(user_id: int | None) -> str:
    """
    Name to print after Best regards / Sincerely — matches Settings + sender account.
    Priority: active sender account display_name → outreach.sender_domain branding → email local part → fallback.
    """
    if user_id is None:
        return "Our team"

    from sqlmodel import select
    from app.storage.database import AsyncSessionLocal
    from app.storage.models import SenderEmailAccountRecord
    from app.services.settings import get_settings

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == user_id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1),
        )
        acc = result.scalar_one_or_none()

    if acc:
        if acc.display_name and acc.display_name.strip():
            return acc.display_name.strip()
        if acc.email_address and "@" in acc.email_address:
            local = acc.email_address.split("@")[0]
            frag = re.split(r"[._-]", local)[0]
            if frag and len(frag) >= 2 and frag.lower() not in _MAILBOX_ALIAS_FIRST_TOKENS:
                return frag[:1].upper() + frag[1:].lower()

    settings = await get_settings(user_id)
    dom = (settings.outreach.sender_domain or "").strip()
    if dom:
        base = dom.split(".")[0].replace("-", " ").strip()
        if base and len(base) >= 2:
            return base[:1].upper() + base[1:].lower() if base.islower() else base

    return "Our team"
