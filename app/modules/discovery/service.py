"""
Discovery Module
----------------
Responsibility: Search Google Maps for companies matching the BusinessContext.
Input:  BusinessContext + pipeline_run_id
Output: list[RawLead]

Query pattern (only non-empty parts included):
  "{industry} {domain} companies in {area} {location}"

Failure strategy:
- Playwright timeout → raise DiscoveryError with context
- No results found  → return empty list (not an error)
- Partial results   → return what was found, log warning
"""

import uuid
from app.schemas import BusinessContext, RawLead
from app.core.exceptions import DiscoveryError
from app.core.logging import get_logger
from app.modules.discovery.scraper import GoogleMapsScraper, WebSearchScraper

logger = get_logger(__name__)


def _build_query(industry: str, context: BusinessContext) -> str:
    """
    Builds a search query entirely from runtime context.
    Nothing is hardcoded — every part comes from what the user supplied.

    Pattern: "{industry} {domain} companies in {area} {location} {country}"
    Only non-empty fields are included.

    Examples:
      industries=["manufacturing"], location="Riyadh", country="Saudi Arabia"
        → "manufacturing companies in Riyadh Saudi Arabia"

      industries=["logistics"], location="Dubai", country="UAE", domain="supply chain"
        → "logistics supply chain companies in Dubai UAE"

      industries=["retail"], location="Cairo"  (no country)
        → "retail companies in Cairo"

      industries=["tech"], location="Riyadh", area="KAFD", country="Saudi Arabia"
        → "tech companies in KAFD Riyadh Saudi Arabia"
    """
    parts: list[str] = [industry]
    if context.domain:
        parts.append(context.domain)
    parts.append("companies in")
    if context.area:
        parts.append(context.area)
    parts.append(context.location)
    if context.country:
        parts.append(context.country)
    return " ".join(parts)


class DiscoveryService:
    def __init__(self) -> None:
        self._maps_scraper = GoogleMapsScraper()
        self._web_scraper  = WebSearchScraper()

    async def discover(
        self,
        context: BusinessContext,
        pipeline_run_id: uuid.UUID | None = None,
    ) -> list[RawLead]:
        leads: list[RawLead] = []

        for industry in context.industries:
            query = _build_query(industry, context)
            logger.info("discovery.search", query=query)

            # Source 1: Google Maps (Playwright)
            try:
                maps_results = await self._maps_scraper.search(
                    query=query,
                    location=context.location,
                    pipeline_run_id=pipeline_run_id,
                )
                leads.extend(maps_results)
                logger.info("discovery.maps.found", industry=industry, count=len(maps_results))
            except DiscoveryError:
                logger.warning("discovery.maps.failed", industry=industry, query=query)

            # Source 2: Google Web Search (httpx) — supplements Maps
            try:
                web_results = await self._web_scraper.search(
                    query=query,
                    location=context.location,
                    pipeline_run_id=pipeline_run_id,
                )
                leads.extend(web_results)
                logger.info("discovery.web.found", industry=industry, count=len(web_results))
            except Exception as e:
                # Web search is supplementary — never fatal
                logger.warning("discovery.web.failed", industry=industry, error=str(e))

        # Coarse dedup by name+location — Filter Layer handles fine dedup
        seen: set[str] = set()
        unique: list[RawLead] = []
        for lead in leads:
            key = f"{lead.company_name.lower()}|{lead.location.lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(lead)

        logger.info("discovery.complete", total_unique=len(unique))
        return unique
