"""
Multi-source data extraction service.
Integrates ScrapGraphAI, Firecrawl, CrawlForAI, LlamaParse, and standard crawlers.
Implements intelligent fallback strategy for maximum data quality.
"""

from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass
from typing import Optional
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


@dataclass
class ExtractionResult:
    """Unified extraction result across all providers."""
    content: str
    metadata: dict
    provider: str
    success: bool
    error: Optional[str] = None


class MultiSourceExtractor:
    """
    Orchestrates extraction across multiple premium providers.
    Priority order (configurable):
      1. ScrapGraphAI (best for structured data, AI-powered)
      2. Firecrawl (reliable, good for modern SPAs)
      3. CrawlForAI (good fallback, handles JS)
      4. LlamaParse (PDF/document focus)
      5. Standard requests (lightweight backup)
    """

    def __init__(self):
        self.scrapgraph_api_key = os.getenv("SCRAPGRAPH_API_KEY")
        self.firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        self.crawlforai_api_key = os.getenv("CRAWLFORAI_API_KEY")
        self.llamaparse_api_key = os.getenv("LLAMAPARSE_API_KEY")

    async def extract(
        self,
        url: str,
        extraction_schema: Optional[dict] = None,
        *,
        retry_on_failure: bool = True,
    ) -> ExtractionResult:
        """
        Extract data from URL using optimal provider strategy.
        Falls back through providers on failure.
        """
        providers = [
            self._extract_scrapgraph,
            self._extract_firecrawl,
            self._extract_crawlforai,
            self._extract_llamaparse,
            self._extract_fallback,
        ]

        last_error = None
        for provider_func in providers:
            try:
                logger.info("extraction.attempting", url=url, provider=provider_func.__name__)
                result = await provider_func(url, extraction_schema)
                if result.success:
                    logger.info("extraction.success", url=url, provider=result.provider)
                    return result
                last_error = result.error
            except Exception as e:
                logger.warning("extraction.provider_failed", provider=provider_func.__name__, error=str(e)[:200])
                last_error = str(e)

        # All providers failed
        logger.error("extraction.all_failed", url=url, last_error=last_error)
        return ExtractionResult(
            content="",
            metadata={"url": url},
            provider="none",
            success=False,
            error=last_error or "All extraction providers failed",
        )

    async def _extract_scrapgraph(
        self,
        url: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """ScrapGraphAI — AI-powered structured extraction."""
        if not self.scrapgraph_api_key:
            return ExtractionResult("", {}, "scrapgraph", False, "API key not configured")

        try:
            # Lazy import to avoid hard dependency
            import scrapgraphai
            client = scrapgraphai.Client(api_key=self.scrapgraph_api_key)

            prompt = schema.get("prompt", "Extract key business information") if schema else "Extract all text content"
            graph_config = {
                "llm": {"model": "openai/gpt-4o", "api_key": os.getenv("OPENAI_API_KEY")},
                "verbose": False,
                "headless": True,
            }

            response = await asyncio.to_thread(
                client.graph_based_scrape,
                url,
                user_prompt=prompt,
                config=graph_config,
            )

            content = response.get("result", "")
            return ExtractionResult(
                content=content,
                metadata={"url": url, "schema": schema},
                provider="scrapgraph",
                success=bool(content),
            )
        except Exception as e:
            return ExtractionResult("", {}, "scrapgraph", False, str(e))

    async def _extract_firecrawl(
        self,
        url: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """Firecrawl — Reliable modern web scraping."""
        if not self.firecrawl_api_key:
            return ExtractionResult("", {}, "firecrawl", False, "API key not configured")

        try:
            from firecrawl import FirecrawlApp
            app = FirecrawlApp(api_key=self.firecrawl_api_key)

            extract_with = schema.get("extraction_schema") if schema else None
            response = await asyncio.to_thread(
                app.scrape_url,
                url,
                {
                    "formats": ["markdown", "html"],
                    "onlyMainContent": True,
                    "extractionSchema": extract_with,
                },
            )

            content = response.get("markdown") or response.get("html", "")
            return ExtractionResult(
                content=content,
                metadata={"url": url, "metadata": response.get("metadata", {})},
                provider="firecrawl",
                success=bool(content),
            )
        except Exception as e:
            return ExtractionResult("", {}, "firecrawl", False, str(e))

    async def _extract_crawlforai(
        self,
        url: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """CrawlForAI — Good fallback with JS support."""
        if not self.crawlforai_api_key:
            return ExtractionResult("", {}, "crawlforai", False, "API key not configured")

        try:
            from crawlforai import CrawlForAI
            client = CrawlForAI(api_key=self.crawlforai_api_key)

            response = await asyncio.to_thread(
                client.crawl,
                url,
                {
                    "format": "markdown",
                    "wait_for_js": True,
                    "timeout": 30000,
                },
            )

            content = response.get("content", "")
            return ExtractionResult(
                content=content,
                metadata={"url": url},
                provider="crawlforai",
                success=bool(content),
            )
        except Exception as e:
            return ExtractionResult("", {}, "crawlforai", False, str(e))

    async def _extract_llamaparse(
        self,
        url: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """LlamaParse — Specialized for documents and structured content."""
        if not self.llamaparse_api_key:
            return ExtractionResult("", {}, "llamaparse", False, "API key not configured")

        try:
            from llama_parse import LlamaParse
            parser = LlamaParse(api_key=self.llamaparse_api_key)

            # LlamaParse works best with documents; fetch content first
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    content = await resp.text()

            parsed = await asyncio.to_thread(parser.parse_file, url)
            result_text = "\n".join([str(doc) for doc in parsed]) if parsed else content

            return ExtractionResult(
                content=result_text,
                metadata={"url": url},
                provider="llamaparse",
                success=bool(result_text),
            )
        except Exception as e:
            return ExtractionResult("", {}, "llamaparse", False, str(e))

    async def _extract_fallback(
        self,
        url: str,
        schema: Optional[dict] = None,
    ) -> ExtractionResult:
        """Lightweight fallback using standard requests."""
        try:
            import aiohttp
            from html2text import html2text

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        return ExtractionResult("", {}, "fallback", False, f"HTTP {resp.status}")
                    html = await resp.text()

            # Convert HTML to markdown
            text = html2text(html)
            return ExtractionResult(
                content=text,
                metadata={"url": url},
                provider="fallback",
                success=bool(text),
            )
        except Exception as e:
            return ExtractionResult("", {}, "fallback", False, str(e))


# Singleton instance
_extractor_instance: Optional[MultiSourceExtractor] = None


def get_extractor() -> MultiSourceExtractor:
    """Get or create the extractor singleton."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = MultiSourceExtractor()
    return _extractor_instance
