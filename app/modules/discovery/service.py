"""
Discovery Module
----------------
Responsibility: Search Google Maps + Web for companies matching the BusinessContext.

Flow:
  BusinessContext
    → Opportunity Query Builder  (generates high-intent queries with industry expansion)
    → GoogleMapsScraper + WebSearchScraper
    → Cross-run deduplication    (skip companies already in DB)
    → list[RawLead]

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

        # ── Generate high-intent queries (with industry expansion) ─────────────
        queries = await build_opportunity_queries(context)
        logger.info("discovery.queries_generated", count=len(queries))

        # ── Run each query against both sources ────────────────────────────────
        for query in queries:
            logger.info("discovery.search", query=query)

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

        # ── Within-run dedup by name+location ─────────────────────────────────
        seen: set[str] = set()
        unique: list[RawLead] = []
        for lead in leads:
            key = f"{lead.company_name.lower()}|{lead.location.lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(lead)

        # ── Cross-run dedup: skip companies already in DB ─────────────────────
        try:
            from app.storage.ops_repository import OpsRepository
            repo = OpsRepository()
            known_keys = await repo.get_known_company_keys(context.location)
            before = len(unique)
            unique = [
                lead for lead in unique
                if f"{lead.company_name.lower()}|{lead.location.lower()}" not in known_keys
            ]
            skipped = before - len(unique)
            if skipped > 0:
                logger.info("discovery.cross_run_dedup", skipped=skipped, remaining=len(unique))
        except Exception as e:
            # Cross-run dedup is best-effort — never block discovery
            logger.warning("discovery.cross_run_dedup.failed", error=str(e))

        logger.info("discovery.complete", total_unique=len(unique))
        return unique
