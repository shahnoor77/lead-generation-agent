"""
Industry Expander — adds related sub-industries and domains to discovery queries.

When a user says "manufacturing", the system should also search for:
  - automobile manufacturing, steel manufacturing, food processing,
    textile manufacturing, pharmaceutical manufacturing, etc.

This is purely rule-based (no LLM cost) and covers the most common
industry families. The operator can always override by specifying
exact industries in the form.

Returns a flat list of expanded search terms to use alongside the
original industries in query generation.
"""

from __future__ import annotations
from app.core.logging import get_logger

logger = get_logger(__name__)

# Industry → related sub-sectors and adjacent domains
# Keys are lowercase. Values are the most commercially relevant sub-sectors.
_INDUSTRY_EXPANSIONS: dict[str, list[str]] = {
    "manufacturing": [
        "automobile manufacturing", "auto parts manufacturer",
        "steel manufacturing", "metal fabrication",
        "food processing", "food manufacturing",
        "textile manufacturing", "garment factory",
        "pharmaceutical manufacturing",
        "chemical manufacturing",
        "plastic manufacturing",
        "electronics manufacturing",
        "furniture manufacturing",
        "packaging manufacturer",
    ],
    "logistics": [
        "freight forwarding", "cargo company",
        "warehousing", "cold chain logistics",
        "last mile delivery", "courier company",
        "supply chain company", "3PL provider",
        "customs clearance", "shipping company",
    ],
    "construction": [
        "general contractor", "civil engineering company",
        "real estate developer", "infrastructure company",
        "building materials supplier",
        "MEP contractor", "fit-out company",
    ],
    "retail": [
        "supermarket chain", "hypermarket",
        "FMCG distributor", "wholesale trader",
        "e-commerce retailer", "fashion retailer",
        "electronics retailer",
    ],
    "healthcare": [
        "hospital", "medical center", "clinic",
        "pharmaceutical company", "medical equipment supplier",
        "diagnostic lab", "dental clinic",
    ],
    "automobile": [
        "car dealership", "auto parts supplier",
        "vehicle assembly", "automobile distributor",
        "fleet management company", "auto repair chain",
    ],
    "food": [
        "food processing company", "bakery chain",
        "beverage manufacturer", "dairy company",
        "restaurant chain", "catering company",
        "food distributor",
    ],
    "energy": [
        "oil and gas company", "power generation company",
        "solar energy company", "utilities company",
        "energy services company",
    ],
    "technology": [
        "IT company", "software company",
        "telecom company", "data center",
        "electronics company",
    ],
    "education": [
        "university", "school", "training institute",
        "e-learning company", "vocational training center",
    ],
    "finance": [
        "bank", "insurance company", "investment firm",
        "microfinance company", "leasing company",
    ],
    "real estate": [
        "property developer", "real estate company",
        "property management company", "construction developer",
    ],
    "agriculture": [
        "farm", "agribusiness", "agricultural company",
        "food processing plant", "irrigation company",
    ],
    "hospitality": [
        "hotel chain", "resort", "catering company",
        "event management company", "travel agency",
    ],
}

# How many related terms to add per industry (keep queries focused)
_MAX_EXPANSIONS_PER_INDUSTRY = 4


def expand_industries(industries: list[str]) -> list[str]:
    """
    Given a list of industries, returns the original list plus
    the most relevant related sub-sectors for each.

    Example:
      expand_industries(["manufacturing"]) →
      ["manufacturing", "automobile manufacturing", "steel manufacturing",
       "food processing", "textile manufacturing"]

    The original industries are always first.
    Related terms are appended after.
    """
    expanded: list[str] = list(industries)  # originals first
    seen = set(i.lower() for i in industries)

    for industry in industries:
        key = industry.lower().strip()

        # Direct match
        related = _INDUSTRY_EXPANSIONS.get(key, [])

        # Partial match — e.g. "automobile" matches "automobile manufacturing"
        if not related:
            for exp_key, exp_values in _INDUSTRY_EXPANSIONS.items():
                if exp_key in key or key in exp_key:
                    related = exp_values
                    break

        for term in related[:_MAX_EXPANSIONS_PER_INDUSTRY]:
            if term.lower() not in seen:
                seen.add(term.lower())
                expanded.append(term)

    if len(expanded) > len(industries):
        logger.info(
            "industry_expander.expanded",
            original=industries,
            added=expanded[len(industries):],
        )

    return expanded
