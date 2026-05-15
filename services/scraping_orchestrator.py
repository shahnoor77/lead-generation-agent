import asyncio
import logging
from typing import Dict, Any, Optional, List
from config.scraping_providers import SCRAPING_CONFIG, ScrapingProvider

logger = logging.getLogger(__name__)

class ScrapingOrchestrator:
    def __init__(self):
        self.providers = {
            ScrapingProvider.SCRAPEGRAPHAI: self._scrapegraphai_scrape,
            ScrapingProvider.FIRECRAWL: self._firecrawl_scrape,
            ScrapingProvider.CRAWL4AI: self._crawl4ai_scrape,
            ScrapingProvider.LLAMAPARSE: self._llamaparse_scrape,
            ScrapingProvider.MEGAPARSER: self._megaparser_scrape,
            ScrapingProvider.DOCLINK: self._doclink_scrape,
        }
        self.priority_order = sorted(
            SCRAPING_CONFIG.items(),
            key=lambda x: x[1]["priority"]
        )

    async def scrape_with_fallback(
        self, url: str, extraction_schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Try scraping with multiple providers with intelligent fallback."""
        for provider_enum, config in self.priority_order:
            if not config["enabled"]:
                continue
            
            try:
                logger.info(f"Attempting {provider_enum.value} for {url}")
                result = await self.providers[provider_enum](url, extraction_schema)
                if result and self._validate_extraction(result, extraction_schema):
                    logger.info(f"Successfully scraped with {provider_enum.value}")
                    return result
            except Exception as e:
                logger.warning(f"{provider_enum.value} failed: {str(e)}")
                continue
        
        logger.error(f"All scraping providers failed for {url}")
        return None

    async def _scrapegraphai_scrape(
        self, url: str, schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            from scrapegraphai.graphs import SmartScraperGraph
            graph_config = {
                "llm": {"api_key": SCRAPING_CONFIG[ScrapingProvider.SCRAPEGRAPHAI]["api_key"]},
                "verbose": False,
            }
            scraper = SmartScraperGraph(
                prompt=self._build_extraction_prompt(schema),
                source=url,
                config=graph_config
            )
            return await asyncio.to_thread(scraper.run)
        except Exception as e:
            logger.error(f"ScrapegraphAI error: {e}")
            return None

    async def _firecrawl_scrape(
        self, url: str, schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            from firecrawl import FirecrawlApp
            app = FirecrawlApp(api_key=SCRAPING_CONFIG[ScrapingProvider.FIRECRAWL]["api_key"])
            result = await asyncio.to_thread(
                app.scrape_url,
                url,
                {"formats": ["markdown", "html"]}
            )
            return self._parse_firecrawl_result(result, schema)
        except Exception as e:
            logger.error(f"Firecrawl error: {e}")
            return None

    async def _crawl4ai_scrape(
        self, url: str, schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            from crawl4ai import AsyncWebCrawler
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url)
                return self._parse_crawl4ai_result(result, schema)
        except Exception as e:
            logger.error(f"Crawl4AI error: {e}")
            return None

    async def _llamaparse_scrape(
        self, url: str, schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            from llama_parse import LlamaParseClient
            client = LlamaParseClient(
                api_key=SCRAPING_CONFIG[ScrapingProvider.LLAMAPARSE]["api_key"]
            )
            result = await asyncio.to_thread(client.parse_document, url)
            return self._parse_llamaparse_result(result, schema)
        except Exception as e:
            logger.error(f"LlamaParse error: {e}")
            return None

    async def _megaparser_scrape(
        self, url: str, schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            from megaparser import MegaParser
            parser = MegaParser(api_key=SCRAPING_CONFIG[ScrapingProvider.MEGAPARSER]["api_key"])
            result = await asyncio.to_thread(parser.parse, url, schema)
            return result
        except Exception as e:
            logger.error(f"MegaParser error: {e}")
            return None

    async def _doclink_scrape(
        self, url: str, schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            from doclink import DoclinkClient
            client = DoclinkClient(api_key=SCRAPING_CONFIG[ScrapingProvider.DOCLINK]["api_key"])
            result = await asyncio.to_thread(client.extract, url)
            return self._parse_doclink_result(result, schema)
        except Exception as e:
            logger.error(f"Doclink error: {e}")
            return None

    def _validate_extraction(self, result: Dict, schema: Dict) -> bool:
        """Validate if extraction met minimum required fields."""
        required_fields = schema.get("required_fields", [])
        return all(field in result and result[field] for field in required_fields)

    def _build_extraction_prompt(self, schema: Dict[str, Any]) -> str:
        return f"Extract the following information: {schema}"

    # ...existing parsing helper methods...
