"""
Discovery scrapers.

Two sources run per query:
  1. GoogleMapsScraper  — Playwright, clicks each listing to get full detail panel
                          (website URL is only reliably available in the detail panel)
  2. WebSearchScraper   — httpx + BeautifulSoup, Google organic results
                          supplements Maps with companies that have websites

Both return list[RawLead]. DiscoveryService deduplicates by name+location.
"""

from __future__ import annotations
import asyncio
import re
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from app.schemas import RawLead, LeadSource
from app.core.config import settings
from app.core.exceptions import DiscoveryError
from app.core.logging import get_logger

logger = get_logger(__name__)

MAPS_SEARCH_URL = "https://www.google.com/maps/search/{query}"
WEB_SEARCH_URL  = "https://www.google.com/search?q={query}&num=20&hl=en"

# Domains to skip in web search results
_SKIP_DOMAINS = {
    "google.com", "google.com.sa", "youtube.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "wikipedia.org", "maps.google.com", "amazon.com", "amazon.sa",
    "tripadvisor.com", "yelp.com", "zomato.com", "foursquare.com",
}


# ──────────────────────────────────────────────────────────────────────────────
# Google Maps scraper (Playwright)
# Strategy: parse the results feed for basic info, then click each listing
# to open the detail panel where the website URL is reliably shown.
# ──────────────────────────────────────────────────────────────────────────────

class GoogleMapsScraper:
    async def search(self, query: str, location: str, pipeline_run_id=None) -> list[RawLead]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                locale="en-US",
                geolocation={"latitude": 24.7136, "longitude": 46.6753},
                permissions=["geolocation"],
            )
            page = await ctx.new_page()

            try:
                url = MAPS_SEARCH_URL.format(query=quote_plus(query))
                await page.goto(url, timeout=settings.scrape_timeout_seconds * 1000)
                await page.wait_for_selector('[role="feed"]', timeout=10_000)
                await self._scroll_results(page)
                return await self._parse_results(page, location, pipeline_run_id)

            except PWTimeout as e:
                raise DiscoveryError(f"Timeout scraping Maps for '{query}': {e}") from e
            except Exception as e:
                raise DiscoveryError(f"Unexpected error scraping Maps: {e}") from e
            finally:
                await browser.close()

    async def _scroll_results(self, page: Page, scrolls: int = 5) -> None:
        feed = page.locator('[role="feed"]')
        for _ in range(scrolls):
            await feed.evaluate("el => el.scrollBy(0, 800)")
            await asyncio.sleep(1.0)

    async def _parse_results(self, page: Page, location: str, pipeline_run_id=None) -> list[RawLead]:
        # Collect all listing links from the feed first
        links = await page.query_selector_all('[role="feed"] a[href*="/maps/place/"]')
        hrefs: list[str] = []
        seen_hrefs: set[str] = set()
        for link in links:
            href = await link.get_attribute("href")
            if href and href not in seen_hrefs:
                seen_hrefs.add(href)
                hrefs.append(href)

        leads: list[RawLead] = []

        for href in hrefs[:20]:  # cap at 20 per query to avoid timeout
            try:
                lead = await self._extract_from_detail(page, href, location, pipeline_run_id)
                if lead:
                    leads.append(lead)
            except Exception as e:
                logger.warning("discovery.maps.detail_failed", error=str(e))
                continue

        return leads

    async def _extract_from_detail(
        self, page: Page, href: str, location: str, pipeline_run_id
    ) -> Optional[RawLead]:
        """Navigate to a listing's detail panel and extract all fields."""
        try:
            await page.goto(href, timeout=15_000)
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            await asyncio.sleep(0.8)
        except Exception:
            return None

        # Company name — h1 in the detail panel
        name = await self._page_text(page, 'h1.DUwDvf, h1[class*="fontHeadlineLarge"]')
        if not name:
            name = await self._page_text(page, "h1")
        if not name:
            return None

        # Category
        category = await self._page_text(page, 'button[jsaction*="category"]')
        if not category:
            category = await self._page_text(page, 'span[jstcache] button')

        # Address
        address = await self._page_attr(
            page,
            'button[data-item-id="address"], [data-tooltip="Copy address"]',
            "aria-label",
        )
        if not address:
            address = await self._page_text(page, '[data-item-id="address"]')

        # Phone
        phone = await self._page_attr(
            page,
            'button[data-item-id^="phone"], [data-tooltip="Copy phone number"]',
            "aria-label",
        )
        if not phone:
            phone = await self._page_text(page, '[data-item-id^="phone"]')

        # Website — try multiple selectors
        website = None
        for sel in [
            'a[data-item-id="authority"]',
            'a[href*="http"][aria-label*="website" i]',
            'a[href*="http"][data-tooltip*="website" i]',
            'a[jsaction*="website"]',
        ]:
            raw = await self._page_attr(page, sel, "href")
            if raw and raw.startswith("http") and "google.com" not in raw:
                website = raw
                break

        # Rating
        rating_text = await self._page_text(page, 'span.ceNzKf, div.F7nice span[aria-hidden="true"]')
        rating: Optional[float] = None
        if rating_text:
            try:
                rating = float(rating_text.replace(",", "."))
            except ValueError:
                pass

        # Review count
        review_text = await self._page_text(page, 'span[aria-label*="review" i]')
        review_count = self._parse_int(review_text)

        return RawLead(
            pipeline_run_id=pipeline_run_id,
            company_name=name.strip(),
            location=location,
            address=address,
            phone=self._clean_label(phone),
            website=website,
            category=category,
            rating=rating,
            review_count=review_count,
        )

    async def _page_text(self, page: Page, selector: str) -> Optional[str]:
        try:
            el = await page.query_selector(selector)
            if not el:
                return None
            return (await el.inner_text()).strip() or None
        except Exception:
            return None

    async def _page_attr(self, page: Page, selector: str, attr: str) -> Optional[str]:
        try:
            el = await page.query_selector(selector)
            if not el:
                return None
            return await el.get_attribute(attr)
        except Exception:
            return None

    def _clean_label(self, text: Optional[str]) -> Optional[str]:
        """Strip 'Phone: ' or 'Address: ' prefixes from aria-label values."""
        if not text:
            return None
        for prefix in ["Phone: ", "Address: ", "Website: "]:
            if text.startswith(prefix):
                return text[len(prefix):]
        return text

    def _parse_int(self, text: Optional[str]) -> Optional[int]:
        if not text:
            return None
        digits = re.sub(r"[^\d]", "", text)
        try:
            return int(digits) if digits else None
        except ValueError:
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Web search scraper (httpx + BeautifulSoup)
# Supplements Maps with companies found via Google organic search.
# ──────────────────────────────────────────────────────────────────────────────

class WebSearchScraper:
    async def search(self, query: str, location: str, pipeline_run_id=None) -> list[RawLead]:
        search_url = WEB_SEARCH_URL.format(query=quote_plus(query))
        leads: list[RawLead] = []

        try:
            async with httpx.AsyncClient(
                timeout=settings.scrape_timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ) as client:
                resp = await client.get(search_url)

            if resp.status_code != 200:
                logger.warning("discovery.web.non200", status=resp.status_code)
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            for result in soup.select("div.g"):
                title_el = result.select_one("h3")
                link_el  = result.select_one("a[href]")
                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                href  = link_el.get("href", "")

                if not href.startswith("http"):
                    continue

                domain = self._extract_domain(href)
                if any(skip in domain for skip in _SKIP_DOMAINS):
                    continue

                company_name = self._clean_title(title)
                if not company_name:
                    continue

                leads.append(RawLead(
                    pipeline_run_id=pipeline_run_id,
                    company_name=company_name,
                    location=location,
                    website=href,
                    source=LeadSource.GOOGLE_MAPS,
                ))

        except Exception as e:
            logger.warning("discovery.web.failed", query=query, error=str(e))

        logger.info("discovery.web.found", query=query, count=len(leads))
        return leads

    def _extract_domain(self, url: str) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            return ""

    def _clean_title(self, title: str) -> str:
        for sep in [" - ", " | ", " – ", " — "]:
            if sep in title:
                title = title.split(sep)[0]
        return title.strip()
