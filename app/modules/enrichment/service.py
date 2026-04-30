"""
Enrichment Module
-----------------
Responsibility: Visit company website, extract structured info, summarize with LLM.
Input:  RawLead
Output: EnrichedLead  (new object — RawLead is never mutated)

Failure strategy:
- No website URL → enrichment_success=False, enrichment_error set, pipeline continues
- Scrape timeout  → same as above
- LLM failure     → raw extracted text used as fallback summary
"""

from app.schemas import RawLead, EnrichedLead, BusinessType
from app.core.logging import get_logger
from app.modules.enrichment.scraper import WebsiteScraper
from app.modules.enrichment.summarizer import WebsiteSummarizer

logger = get_logger(__name__)


class EnrichmentService:
    def __init__(self) -> None:
        self._scraper = WebsiteScraper()
        self._summarizer = WebsiteSummarizer()

    async def enrich(self, lead: RawLead) -> EnrichedLead:
        base = dict(
            lead_id=lead.lead_id,
            trace_id=lead.trace_id,
            pipeline_run_id=lead.pipeline_run_id,
            source=lead.source,
            discovered_at=lead.discovered_at,
            company_name=lead.company_name,
            location=lead.location,
            category=lead.category,
            website=lead.website,
            phone=lead.phone,
            address=lead.address,
            rating=lead.rating,
            review_count=lead.review_count,
        )

        if not lead.website:
            logger.info("enrichment.skipped", lead_id=str(lead.lead_id), reason="no_website")
            return EnrichedLead(
                **base,
                enrichment_success=False,
                enrichment_error="no_website_url",
            )

        logger.info("enrichment.start", lead_id=str(lead.lead_id), url=str(lead.website))

        try:
            raw_data = await self._scraper.extract(str(lead.website))
        except Exception as e:
            logger.warning("enrichment.scrape_failed", lead_id=str(lead.lead_id), error=str(e))
            return EnrichedLead(
                **base,
                enrichment_success=False,
                enrichment_error=f"scrape_failed: {e}",
            )

        # LLM summarization — non-blocking failure
        summary: str | None = None
        try:
            summary = await self._summarizer.summarize(
                company_name=lead.company_name,
                raw_text=raw_data.get("full_text", ""),
                category=lead.category,
                location=lead.location,
            )
        except Exception as e:
            logger.warning("enrichment.summarize_failed", lead_id=str(lead.lead_id), error=str(e))
            summary = raw_data.get("full_text", "")[:500] or None

        # Ensure summary is never None when enrichment_success=True
        # (schema validator requires it)
        if not summary:
            summary = f"{lead.company_name} — website scraped but summary unavailable."

        logger.info("enrichment.complete", lead_id=str(lead.lead_id))
        return EnrichedLead(
            **base,
            enrichment_success=True,
            summary=summary,
            services_detected=raw_data.get("services", []),
            key_people=raw_data.get("key_people", []),
            contact_email=raw_data.get("email"),
            linkedin_url=raw_data.get("linkedin"),
            founding_year=raw_data.get("founding_year"),
            employee_count_hint=raw_data.get("employee_count_hint"),
            language_of_website=raw_data.get("language"),
            business_type=BusinessType.UNKNOWN,
        )
