"""
Opportunity Query Builder — intelligent context-aware query generation.

Improvements:
- Context understanding: derives implicit signals from industry + service combinations
- Synonym expansion: adds industry synonyms and related terms automatically
- Broad + precise: generates both specific and broader queries for richer results
- LLM generates buyer-intent phrasing when context is rich enough
- Rule-based always runs as safety net
"""

from __future__ import annotations
import json

from app.schemas import BusinessContext
from app.core.config import settings
from app.core.logging import get_logger
from app.utils.llm_client import llm_chat
from app.modules.discovery.industry_expander import expand_industries

logger = get_logger(__name__)


# ── Industry synonyms and related search terms ────────────────────────────────
# These broaden searches to catch companies that don't use the exact industry word

_INDUSTRY_SYNONYMS: dict[str, list[str]] = {
    "manufacturing": ["production company", "factory", "industrial company", "plant"],
    "logistics": ["freight company", "shipping company", "supply chain", "cargo"],
    "construction": ["builder", "contractor", "developer", "infrastructure"],
    "retail": ["trading company", "distributor", "wholesale", "merchant"],
    "healthcare": ["medical", "hospital", "clinic", "health services"],
    "automobile": ["auto", "vehicle", "car dealer", "automotive"],
    "food": ["food processing", "FMCG", "beverage", "food production"],
    "technology": ["IT company", "tech firm", "software company"],
    "education": ["school", "institute", "training center", "academy"],
    "energy": ["oil and gas", "power company", "utilities"],
    "real estate": ["property developer", "real estate company", "construction developer"],
    "finance": ["bank", "financial services", "investment company"],
    "hospitality": ["hotel", "resort", "catering"],
    "agriculture": ["farm", "agribusiness", "agricultural company"],
}

# Context signals: if user provides these services, add these search angle terms
_SERVICE_TO_BUYER_SIGNALS: dict[str, list[str]] = {
    "erp": ["operations", "enterprise", "multi-site"],
    "automation": ["manual process", "production line", "operations"],
    "ai": ["data-driven", "analytics", "operations"],
    "supply chain": ["procurement", "inventory", "distribution"],
    "digital transformation": ["legacy systems", "modernization", "operations"],
    "crm": ["sales team", "customer management", "B2B sales"],
    "hr": ["workforce", "employees", "talent management"],
    "accounting": ["finance team", "bookkeeping", "financial management"],
}


def _get_buyer_angle_terms(context: BusinessContext) -> list[str]:
    """Derive implicit buyer-signal terms from our_services."""
    terms: list[str] = []
    for service in context.our_services:
        service_lower = service.lower()
        for key, signals in _SERVICE_TO_BUYER_SIGNALS.items():
            if key in service_lower:
                terms.extend(signals[:2])
    return list(dict.fromkeys(terms))[:4]  # dedupe, cap at 4


def build_rule_based_queries(context: BusinessContext) -> list[str]:
    """
    Generates broad + precise queries using context signals without LLM.

    Strategy:
    1. Expand industries to sub-sectors
    2. Add industry synonyms for broader coverage
    3. Add pain-pattern variants
    4. Add buyer-angle variants derived from our_services
    """
    queries: list[str] = []
    location_suffix = _location_suffix(context)

    # Expand industries to include related sub-sectors
    expanded = expand_industries(context.industries)

    # Add synonyms for original industries only (not sub-sectors)
    synonym_terms: list[str] = []
    for ind in context.industries:
        syns = _INDUSTRY_SYNONYMS.get(ind.lower(), [])
        synonym_terms.extend(syns[:2])  # max 2 synonyms per industry

    all_terms = expanded + [s for s in synonym_terms if s not in expanded]

    # Buyer angle terms from our_services
    buyer_angles = _get_buyer_angle_terms(context)

    for term in all_terms:
        # Variant 1: pain-pattern query
        if context.target_pain_patterns:
            for pattern in context.target_pain_patterns[:2]:
                queries.append(f"{term} businesses with {pattern}{location_suffix}")

        # Variant 2: buyer-angle query (if we have service signals)
        if buyer_angles:
            queries.append(f"{term} {buyer_angles[0]} companies{location_suffix}")

        # Variant 3: baseline
        queries.append(_build_baseline(term, context, location_suffix))

    # Deduplicate
    seen: set[str] = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    logger.info("query_builder.rule_based",
                count=len(unique), original_industries=context.industries)
    return unique


def _build_baseline(term: str, context: BusinessContext, location_suffix: str) -> str:
    parts = [term, "companies in"]
    if context.area:
        parts.append(context.area)
    parts.append(context.location)
    if context.country:
        parts.append(context.country)
    return " ".join(parts)


def _location_suffix(context: BusinessContext) -> str:
    parts = []
    if context.area:
        parts.append(f"in {context.area}")
    parts.append(f"in {context.location}")
    if context.country:
        parts.append(context.country)
    return " " + " ".join(parts) if parts else ""


# ── LLM-enhanced query builder ────────────────────────────────────────────────

_PROMPT = """You are a B2B sales targeting expert with deep knowledge of business search.

Generate {count} search queries to find companies that are likely BUYERS of our services.
Include BOTH precise queries AND broader related queries to maximize discovery coverage.

Context:
- Industries we target: {industries}
- Related buyer signals: {buyer_signals}
- Location: {location}
- Pain patterns in target companies: {pain_patterns}
- Notes: {notes}

RULES:
1. Find TARGET COMPANIES (manufacturers, operators, hospitals, etc.) — NOT service providers
2. Mix precise queries ("steel manufacturers in Lahore") with broader ones ("industrial companies in Lahore")
3. Use local business terminology when relevant
4. Include location in every query
5. Keep each query under 12 words
6. Output valid JSON only: {{"queries": ["...", ...]}}

Generate exactly {count} queries — half precise, half broader."""


async def build_llm_queries(
    context: BusinessContext,
    count: int = 8,
    user_id: int | None = None,
) -> list[str]:
    has_signal = bool(context.domain or context.target_pain_patterns or context.our_services)
    if not has_signal:
        return build_rule_based_queries(context)

    buyer_signals = _get_buyer_angle_terms(context)

    try:
        prompt = _PROMPT.format(
            count=count,
            industries=", ".join(expand_industries(context.industries)[:6]),
            buyer_signals=", ".join(buyer_signals) if buyer_signals else "N/A",
            pain_patterns=", ".join(context.target_pain_patterns) if context.target_pain_patterns else "N/A",
            location=f"{context.location}{', ' + context.country if context.country else ''}",
            notes=context.notes or "N/A",
        )

        response = await llm_chat(
            messages=[
                {"role": "system", "content": "You are a JSON-only responder."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.4,
            user_id=user_id,
        )

        raw = (response.choices[0].message.content or "{}").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        llm_queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]

        if not llm_queries:
            raise ValueError("empty")

        baselines = build_rule_based_queries(context)
        combined = llm_queries + [b for b in baselines if b not in llm_queries]
        logger.info("query_builder.llm_success", total=len(combined))
        return combined

    except Exception as e:
        logger.warning("query_builder.llm_failed", error=str(e))
        return build_rule_based_queries(context)


async def build_opportunity_queries(
    context: BusinessContext,
    user_id: int | None = None,
) -> list[str]:
    queries = await build_llm_queries(context, user_id=user_id)
    if not queries:
        queries = [_build_baseline(ind, context, _location_suffix(context))
                   for ind in context.industries]
    logger.info("query_builder.final", count=len(queries))
    return queries
