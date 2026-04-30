"""
Discovery Module
----------------
Responsibility: Search Google Maps + Web for companies matching the BusinessContext.

Flow (Phase 1.5):
  BusinessContext
    → Opportunity Query Builder  (generates high-intent queries)
    → GoogleMapsScraper          (Playwright, detail-click)
    → WebSearchScraper           (httpx + BeautifulSoup)
    → dedup
    → list[RawLead]

The query builder replaces the old _build_query() function.
Discovery modules are unchanged — they just receive better queries.

Failure strategy:
- Query builder failure → falls back to baseline queries (never blocks)
- Maps timeout → that query skipped, others continue
- Web search failure → supplementary, never fatal
"""

import uuid
from app.schemas import BusinessContext, RawLead
from app.core.exceptions import DiscoveryError
from app.core.logging import get_logger
from app.modules.discovery.scraper import GoogleMapsScraper, WebSearchScraper
from app.modules.discovery.query_builder import build_opportunity_queries

logger = get_logger(__name__)


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

        # ── Phase 1.5: Generate high-intent queries ────────────────────────────
        queries = await build_opportunity_queries(context)
        logger.info("discovery.queries_generated", count=len(queries), queries=queries)

        # ── Run each query against both sources ────────────────────────────────
        for query in queries:
            logger.info("discovery.search", query=query)

            # Source 1: Google Maps (Playwright — detail-click for website)
            try:
                maps_results = await self._maps_scraper.search(
                    query=query,
                    location=context.location,
                    pipeline_run_id=pipeline_run_id,
                )
                leads.extend(maps_results)
                logger.info("discovery.maps.found", query=query, count=len(maps_results))
            except DiscoveryError:
                logger.warning("discovery.maps.failed", query=query)

            # Source 2: Google Web Search (httpx — supplementary)
            try:
                web_results = await self._web_scraper.search(
                    query=query,
                    location=context.location,
                    pipeline_run_id=pipeline_run_id,
                )
                leads.extend(web_results)
                logger.info("discovery.web.found", query=query, count=len(web_results))
            except Exception as e:
                logger.warning("discovery.web.failed", query=query, error=str(e))

        # ── Coarse dedup by name+location ──────────────────────────────────────
        # Filter Layer handles fine dedup (duplicate lead_id within a run)
        seen: set[str] = set()
        unique: list[RawLead] = []
        for lead in leads:
            key = f"{lead.company_name.lower()}|{lead.location.lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(lead)

        logger.info("discovery.complete", total_unique=len(unique))
        return unique
