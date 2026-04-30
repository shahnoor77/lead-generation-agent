"""
Opportunity Query Builder — Phase 1.5 Chunk 1

Sits between BusinessContext and Discovery.
Generates high-intent search queries that target likely buyers,
not just companies that exist in an industry.

Design principles:
- Fully runtime-driven — no hardcoded business assumptions
- Works for any service type: ERP, AI, logistics, healthcare, construction, etc.
- Two query strategies:
    1. Rule-based (fast, always runs) — combines context signals intelligently
    2. LLM-enhanced (optional, richer) — generates buyer-intent phrasing when
       our_services or target_pain_patterns are provided
- Falls back to rule-based if LLM is unavailable
- Returns list[str] — one query per intent angle, not just one per industry

The Discovery module iterates over these queries instead of building its own.
"""

from __future__ import annotations
import json
from openai import AsyncOpenAI

from app.schemas import BusinessContext
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=60.0,
)


# ──────────────────────────────────────────────────────────────────────────────
# Rule-based query builder (fast, no LLM, always available)
# ──────────────────────────────────────────────────────────────────────────────

def build_rule_based_queries(context: BusinessContext) -> list[str]:
    """
    Generates high-intent queries using context signals without LLM.

    CRITICAL RULE: our_services (what WE sell) must NEVER appear in search queries.
    Searching for "manufacturing AI automation companies" finds AI companies, not manufacturers.
    our_services is used for ICP scoring and outreach — not for discovery.

    Strategy per industry:
    - Variant 1: industry + pain pattern (if provided) — targets companies showing buying signals
    - Variant 2: industry + domain baseline (always) — broad industry search
    """
    queries: list[str] = []
    location_suffix = _location_suffix(context)

    for industry in context.industries:
        # Variant 1: pain-pattern query — targets companies showing operational signals
        # Uses target_pain_patterns (what THEY experience), NOT our_services (what WE sell)
        if context.target_pain_patterns:
            for pattern in context.target_pain_patterns[:2]:
                q = f"{industry} businesses with {pattern}{location_suffix}"
                queries.append(q)

        # Variant 2: domain-enriched baseline (always included)
        # domain = what THEY do (e.g. "automobile", "supply chain") — safe to include
        baseline = _build_baseline(industry, context, location_suffix)
        queries.append(baseline)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    logger.info("query_builder.rule_based", count=len(unique), queries=unique)
    return unique


def _build_baseline(industry: str, context: BusinessContext, location_suffix: str) -> str:
    """
    Baseline query: industry + location only.
    domain is intentionally excluded — it's too ambiguous and pollutes results.
    Only the industry name (what THEY do) + location drives Google Maps searches.
    """
    parts = [industry, "companies in"]
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


# ──────────────────────────────────────────────────────────────────────────────
# LLM-enhanced query builder (richer, buyer-intent phrasing)
# ──────────────────────────────────────────────────────────────────────────────

_PROMPT = """You are a B2B sales targeting expert.

Generate {count} high-intent search queries to find companies that are likely BUYERS of our services.

Context:
- Industries we target (what THEY do): {industries}
- Their business domain: {domain}
- Location: {location}
- Pain patterns we look for in target companies: {pain_patterns}
- Notes: {notes}

CRITICAL RULES:
1. Queries must find TARGET COMPANIES (manufacturers, operators, hospitals, retailers, etc.)
2. Do NOT include our service names in queries — that finds our competitors, not our customers
3. Use the industry + domain + location + pain patterns to find BUYERS
4. Include location in every query
5. Use buyer-profile language: "manufacturers in", "logistics operators in", "factories in"
6. Keep each query under 12 words
7. Output valid JSON only: {{"queries": ["...", "...", ...]}}

Generate exactly {count} queries that find companies who NEED our services, not companies that SELL them."""


async def build_llm_queries(context: BusinessContext, count: int = 6) -> list[str]:
    """
    Uses LLM to generate buyer-intent queries.
    Falls back to rule-based on any failure.
    """
    # Only call LLM if we have domain or pain patterns to improve on rule-based
    has_signal = bool(context.domain or context.target_pain_patterns)
    if not has_signal:
        logger.info("query_builder.llm_skipped", reason="no_domain_or_pain_signal")
        return build_rule_based_queries(context)

    try:
        prompt = _PROMPT.format(
            count=count,
            industries=", ".join(context.industries),
            domain=context.domain or "N/A",
            pain_patterns=", ".join(context.target_pain_patterns) if context.target_pain_patterns else "N/A",
            location=f"{context.location}{', ' + context.country if context.country else ''}",
            notes=context.notes or "N/A",
        )

        response = await client.chat.completions.create(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": "You are a JSON-only responder. Output valid JSON and nothing else."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.3,
        )

        raw = response.choices[0].message.content or "{}"
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]

        if not queries:
            raise ValueError("LLM returned empty query list")

        # Always include rule-based baselines as safety net
        baselines = build_rule_based_queries(context)
        combined = queries + [b for b in baselines if b not in queries]

        logger.info("query_builder.llm_success", llm_count=len(queries), total=len(combined))
        return combined

    except Exception as e:
        logger.warning("query_builder.llm_failed", error=str(e))
        return build_rule_based_queries(context)


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────

async def build_opportunity_queries(context: BusinessContext) -> list[str]:
    """
    Main entry point for the Opportunity Query Builder.
    Called by DiscoveryService before scraping.

    Returns a deduplicated list of high-intent search queries.
    Always returns at least one query (falls back to baseline).
    """
    queries = await build_llm_queries(context)

    if not queries:
        # Last-resort fallback
        queries = [_build_baseline(ind, context, _location_suffix(context)) for ind in context.industries]

    logger.info("query_builder.final", count=len(queries))
    return queries
