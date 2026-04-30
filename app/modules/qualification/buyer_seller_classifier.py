"""
Buyer vs Seller Classifier — Phase 1.5 Chunk 2

Determines whether a company is likely a BUYER of our services
or a SELLER/PROVIDER of the same services (competitor/vendor).

Design:
- Rule-based classification is PRIMARY — always runs, never fails
- LLM is OPTIONAL tie-breaker for UNCERTAIN cases only
- Returns BuyerSellerResult with scores, classification, signals, and reasoning
- Fully runtime-driven — no hardcoded business assumptions
- Works for any service type: ERP, AI, logistics, healthcare, construction, etc.

Classification:
  BUYER      — company likely needs our services (manufacturer, operator, etc.)
  SELLER     — company likely sells the same services (consultant, agency, etc.)
  UNCERTAIN  — insufficient signal to classify confidently

ICP integration:
  SELLER  → heavy penalty on rule_score (subtract 40 points, cap at 20)
  BUYER   → small bonus (add 5 points, cap at 100)
  UNCERTAIN → no change
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from enum import Enum

from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnrichedLead, BusinessContext

logger = get_logger(__name__)

client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=60.0,
)


# ──────────────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────────────

class BuyerSellerLabel(str, Enum):
    BUYER     = "BUYER"
    SELLER    = "SELLER"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class BuyerSellerResult:
    classification: BuyerSellerLabel
    buyer_score: int        # 0–100: how strongly this looks like a buyer
    seller_score: int       # 0–100: how strongly this looks like a seller/provider
    buyer_signals: list[str] = field(default_factory=list)   # matched buyer keywords
    seller_signals: list[str] = field(default_factory=list)  # matched seller keywords
    reasoning: str = ""
    llm_used: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Generic seller/provider patterns (extensible, not business-specific)
# These indicate a company SELLS services rather than BUYS them.
# ──────────────────────────────────────────────────────────────────────────────

_SELLER_PATTERNS: list[str] = [
    # Service/consulting identity words
    "consulting", "consultancy", "consultants", "consultant",
    "advisory", "advisors", "advisor",
    "solutions provider", "solutions company", "solutions firm",
    "implementation partner", "implementation services",
    "system integrator", "systems integrator",
    "agency", "agencies",
    "services company", "services firm", "services provider",
    "transformation experts", "transformation consultancy",
    "digital agency", "tech agency",
    "outsourcing", "managed services",
    "professional services",
    "it services", "it consulting",
    "software house", "software company", "software solutions",
    "technology partner", "tech partner",
    "vendor", "reseller", "distributor of software",
    "erp partner", "erp vendor", "erp consultant",
    "sap partner", "oracle partner", "microsoft partner",
    "certified partner", "gold partner", "platinum partner",
    # Tech/IT company signals (these are sellers of tech, not buyers of ops services)
    "innovations", "technologies", "tech solutions", "digital solutions",
    "software development", "app development", "web development",
    "it company", "tech company", "technology company",
    "coding", "developers", "development company",
]

# Patterns that, when combined with our_services keywords, strongly indicate seller
_SELLER_SUFFIX_PATTERNS: list[str] = [
    "consulting", "consultancy", "solutions", "services",
    "advisory", "partners", "group", "experts", "agency",
]

# ──────────────────────────────────────────────────────────────────────────────
# Generic buyer patterns (companies that USE services, not sell them)
# ──────────────────────────────────────────────────────────────────────────────

_BUYER_PATTERNS: list[str] = [
    # Operations / production
    "manufacturer", "manufacturing", "factory", "factories", "plant", "plants",
    "production", "assembly", "fabrication",
    # Logistics / supply chain
    "logistics", "freight", "shipping", "warehouse", "warehousing",
    "distribution", "distributor", "supply chain", "cargo", "transport",
    # Retail / commerce
    "retailer", "retail", "supermarket", "hypermarket", "store", "shop",
    "trading", "trader", "import", "export",
    # Construction / real estate
    "construction", "contractor", "builder", "developer", "real estate",
    "infrastructure", "engineering firm",
    # Healthcare / pharma
    "hospital", "clinic", "healthcare", "medical center", "pharmacy",
    "pharmaceutical", "lab", "laboratory",
    # Energy / utilities
    "energy", "oil", "gas", "power", "utility", "utilities",
    # Food / agriculture
    "food", "beverage", "agriculture", "farm", "dairy", "processing",
    # Finance (as buyer of ops tools)
    "bank", "insurance", "financial services", "investment",
    # Education
    "university", "school", "college", "institute", "academy",
    # Government / public sector
    "government", "ministry", "municipality", "authority",
]


# ──────────────────────────────────────────────────────────────────────────────
# Rule-based classifier (PRIMARY — always runs)
# ──────────────────────────────────────────────────────────────────────────────

def classify_rule_based(
    lead: EnrichedLead,
    context: BusinessContext,
) -> BuyerSellerResult:
    """
    Deterministic rule-based buyer/seller classification.

    Builds a text corpus from all available lead signals, then:
    1. Checks for seller patterns (generic + service-specific)
    2. Checks for buyer patterns
    3. Computes scores and returns classification

    Thresholds (safe, not over-aggressive):
      seller_score >= 60 → SELLER
      buyer_score  >= 50 → BUYER
      otherwise          → UNCERTAIN
    """
    # Build corpus from all available signals
    corpus_parts = [
        lead.company_name,
        lead.category or "",
        lead.summary or "",
        lead.industry or "",
        " ".join(lead.services_detected),
    ]
    corpus = " ".join(corpus_parts).lower()

    # ── Seller signal detection ────────────────────────────────────────────────
    seller_signals: list[str] = []

    # 1. Generic seller patterns
    for pattern in _SELLER_PATTERNS:
        if pattern in corpus:
            seller_signals.append(pattern)

    # 2. Service-specific seller detection:
    #    If company name/summary contains our service keywords + seller suffix
    #    e.g. "ERP consulting firm" when our_services=["ERP consulting"]
    if context.our_services:
        for service in context.our_services:
            service_lower = service.lower()
            # Check if the company appears to SELL this service
            for suffix in _SELLER_SUFFIX_PATTERNS:
                if service_lower in corpus and suffix in corpus:
                    signal = f"{service_lower}+{suffix}"
                    if signal not in seller_signals:
                        seller_signals.append(signal)

    # ── Buyer signal detection ─────────────────────────────────────────────────
    buyer_signals: list[str] = []
    for pattern in _BUYER_PATTERNS:
        if pattern in corpus:
            buyer_signals.append(pattern)

    # ── Score computation ──────────────────────────────────────────────────────
    # Each unique signal contributes; diminishing returns after 3 signals
    seller_score = min(100, len(seller_signals) * 25)
    buyer_score  = min(100, len(buyer_signals)  * 20)

    # Company name is the strongest signal — if it contains a seller pattern, boost score
    name_lower = lead.company_name.lower()
    name_seller_signals = [s for s in seller_signals if s in name_lower]
    if name_seller_signals:
        seller_score = min(100, seller_score + 30)  # name match is high confidence

    # Seller signals are stronger evidence — if both present, seller wins
    if seller_score >= buyer_score and seller_score > 0:
        buyer_score = max(0, buyer_score - 15)  # dampen buyer score when seller signals present

    # ── Classification ─────────────────────────────────────────────────────────
    if seller_score >= 60:
        label = BuyerSellerLabel.SELLER
        reasoning = f"Seller signals detected: {seller_signals[:3]}. Company likely provides services similar to ours."
    elif buyer_score >= 40:
        label = BuyerSellerLabel.BUYER
        reasoning = f"Buyer signals detected: {buyer_signals[:3]}. Company likely needs our services."
    else:
        label = BuyerSellerLabel.UNCERTAIN
        reasoning = (
            f"Insufficient signal. Seller signals: {seller_signals[:2]}, "
            f"Buyer signals: {buyer_signals[:2]}."
        )

    logger.debug(
        "buyer_seller.rule_based",
        lead_id=str(lead.lead_id),
        classification=label.value,
        seller_score=seller_score,
        buyer_score=buyer_score,
    )

    return BuyerSellerResult(
        classification=label,
        buyer_score=buyer_score,
        seller_score=seller_score,
        buyer_signals=buyer_signals,
        seller_signals=seller_signals,
        reasoning=reasoning,
        llm_used=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# LLM tie-breaker (OPTIONAL — only for UNCERTAIN cases)
# ──────────────────────────────────────────────────────────────────────────────

_LLM_PROMPT = """You are a B2B sales qualification expert.

Determine whether the following company is more likely to BUY our services or SELL the same services.

Our services: {our_services}
Our domain: {domain}

Company: {company_name}
Category: {category}
Summary: {summary}
Services detected: {services}

Answer with valid JSON only:
{{
  "classification": "BUYER" | "SELLER" | "UNCERTAIN",
  "confidence": 0.0-1.0,
  "reasoning": "1 sentence explanation"
}}

Rules:
- BUYER: company needs our services (manufacturer, operator, hospital, retailer, etc.)
- SELLER: company sells the same or similar services (consultant, agency, partner, etc.)
- UNCERTAIN: cannot determine from available information
- Output JSON only. No markdown."""


async def classify_llm_tiebreaker(
    lead: EnrichedLead,
    context: BusinessContext,
    rule_result: BuyerSellerResult,
) -> BuyerSellerResult:
    """
    LLM tie-breaker for UNCERTAIN classifications only.
    Rule-based result is always the fallback.
    """
    if rule_result.classification != BuyerSellerLabel.UNCERTAIN:
        return rule_result  # rule-based was confident — no LLM needed

    if not context.our_services and not context.domain:
        return rule_result  # not enough context for LLM to reason about

    try:
        prompt = _LLM_PROMPT.format(
            our_services=", ".join(context.our_services) if context.our_services else "N/A",
            domain=context.domain or "N/A",
            company_name=lead.company_name,
            category=lead.category or "N/A",
            summary=(lead.summary or "N/A")[:500],
            services=", ".join(lead.services_detected[:5]) if lead.services_detected else "N/A",
        )

        response = await client.chat.completions.create(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": "You are a JSON-only responder."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=150,
            temperature=0.1,
        )

        raw = response.choices[0].message.content or "{}"
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)

        label_str = data.get("classification", "UNCERTAIN").upper()
        label = BuyerSellerLabel(label_str) if label_str in BuyerSellerLabel._value2member_map_ else BuyerSellerLabel.UNCERTAIN
        llm_reasoning = data.get("reasoning", "")

        # LLM can only resolve UNCERTAIN — it cannot override a confident rule result
        updated = BuyerSellerResult(
            classification=label,
            buyer_score=rule_result.buyer_score,
            seller_score=rule_result.seller_score,
            buyer_signals=rule_result.buyer_signals,
            seller_signals=rule_result.seller_signals,
            reasoning=f"[Rule: {rule_result.reasoning}] [LLM: {llm_reasoning}]",
            llm_used=True,
        )

        logger.info(
            "buyer_seller.llm_tiebreaker",
            lead_id=str(lead.lead_id),
            rule_classification=rule_result.classification.value,
            llm_classification=label.value,
        )
        return updated

    except Exception as e:
        logger.warning("buyer_seller.llm_failed", lead_id=str(lead.lead_id), error=str(e))
        return rule_result  # always fall back to rule-based


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────

async def classify_buyer_seller(
    lead: EnrichedLead,
    context: BusinessContext,
) -> BuyerSellerResult:
    """
    Main entry point. Always returns a BuyerSellerResult.
    Rule-based runs first. LLM only called for UNCERTAIN cases.
    """
    rule_result = classify_rule_based(lead, context)

    if rule_result.classification == BuyerSellerLabel.UNCERTAIN:
        return await classify_llm_tiebreaker(lead, context, rule_result)

    return rule_result


# ──────────────────────────────────────────────────────────────────────────────
# ICP score adjustment
# ──────────────────────────────────────────────────────────────────────────────

def apply_buyer_seller_penalty(
    rule_score: int,
    result: BuyerSellerResult,
) -> tuple[int, str | None]:
    """
    Adjusts rule_score based on buyer/seller classification.

    Returns (adjusted_score, penalty_reason).

    SELLER  → subtract 40, floor at 10 (hard penalty — likely competitor)
    BUYER   → add 5, cap at 100 (small bonus — confirmed buyer signal)
    UNCERTAIN → no change
    """
    if result.classification == BuyerSellerLabel.SELLER:
        adjusted = max(10, rule_score - 40)
        reason = f"Seller/provider penalty: {result.reasoning}"
        logger.info(
            "buyer_seller.penalty_applied",
            original=rule_score,
            adjusted=adjusted,
            classification="SELLER",
        )
        return adjusted, reason

    if result.classification == BuyerSellerLabel.BUYER:
        adjusted = min(100, rule_score + 5)
        return adjusted, None

    return rule_score, None  # UNCERTAIN — no change
