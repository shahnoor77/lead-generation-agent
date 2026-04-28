"""
Discovery Sanity Test
---------------------
Runs a real Google Maps scrape for one keyword and prints results.
Use this BEFORE running the full pipeline to verify:
  - Playwright selectors still match Google Maps HTML
  - RawLead fields are populated correctly
  - At least 5 results are returned

Run with:
    pytest tests/test_discovery_sanity.py -v -s

Or standalone:
    python tests/test_discovery_sanity.py

Requires: playwright install chromium
"""

import asyncio
import uuid
import pytest

from app.schemas import BusinessContext, OutreachLanguage
from app.modules.discovery.service import DiscoveryService


SANITY_CONTEXT = BusinessContext(
    industries=["manufacturing"],
    location="Riyadh",
    excluded_categories=["restaurant"],
    pain_points=["operational inefficiency"],
    value_proposition="We help KSA enterprises cut costs by 30% in 90 days.",
    language_preference=OutreachLanguage.AR,
)


@pytest.mark.asyncio
async def test_discovery_returns_results() -> None:
    """Verify scraper returns at least 5 leads with required fields populated."""
    svc = DiscoveryService()
    run_id = uuid.uuid4()

    leads = await svc.discover(SANITY_CONTEXT, pipeline_run_id=run_id)

    print(f"\n── Discovery results: {len(leads)} leads ──")
    for i, lead in enumerate(leads[:5], 1):
        print(
            f"  {i}. {lead.company_name!r:40s} "
            f"cat={lead.category or 'N/A':20s} "
            f"website={'yes' if lead.website else 'no ':3s} "
            f"phone={'yes' if lead.phone else 'no'}"
        )

    # Minimum bar: at least 5 results
    assert len(leads) >= 5, (
        f"Expected >= 5 leads, got {len(leads)}. "
        "Playwright selectors may be stale — inspect Google Maps HTML."
    )

    # Every lead must have the required fields
    for lead in leads:
        assert lead.lead_id is not None
        assert lead.trace_id is not None
        assert lead.pipeline_run_id == run_id
        assert lead.company_name.strip() != ""
        assert lead.location == "Riyadh"

    # At least half should have a category (selector sanity)
    with_category = sum(1 for l in leads if l.category)
    print(f"  Leads with category: {with_category}/{len(leads)}")
    assert with_category >= len(leads) // 2, (
        "Too few leads have a category — 'button.DkEaL' selector may be stale."
    )


# ── Standalone runner ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _main() -> None:
        svc = DiscoveryService()
        run_id = uuid.uuid4()
        leads = await svc.discover(SANITY_CONTEXT, pipeline_run_id=run_id)
        print(f"\nTotal leads found: {len(leads)}")
        for lead in leads:
            print(f"  {lead.company_name} | {lead.category} | {lead.website} | {lead.phone}")

    asyncio.run(_main())
