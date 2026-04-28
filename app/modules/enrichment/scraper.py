"""
Website scraper: fetches homepage + /about page, extracts structured signals.
Uses httpx (fast, async) with BeautifulSoup for parsing.
Playwright fallback for JS-heavy sites.
"""

from __future__ import annotations
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/company/[^\s\"'<>]+")
YEAR_RE = re.compile(r"\b(19[89]\d|20[012]\d)\b")


class WebsiteScraper:
    async def extract(self, url: str) -> dict[str, Any]:
        pages_text: list[str] = []

        async with httpx.AsyncClient(
            timeout=settings.scrape_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadBot/1.0)"},
        ) as client:
            for path in ["", "/about", "/about-us", "/من-نحن"]:
                try:
                    resp = await client.get(url.rstrip("/") + path)
                    if resp.status_code == 200:
                        pages_text.append(resp.text)
                except Exception:
                    continue

        if not pages_text:
            raise RuntimeError(f"Could not fetch any page from {url}")

        combined_html = "\n".join(pages_text)
        soup = BeautifulSoup(combined_html, "lxml")

        # strip scripts/styles
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        full_text = soup.get_text(separator=" ", strip=True)

        return {
            "full_text": full_text[:4000],  # cap for LLM context
            "email": self._first(EMAIL_RE.findall(full_text)),
            "linkedin": self._first(LINKEDIN_RE.findall(combined_html)),
            "founding_year": self._founding_year(full_text),
            "services": self._extract_services(soup),
            "key_people": self._extract_people(soup),
            "employee_count_hint": None,  # not reliably extractable from website
            "language": self._detect_language(full_text),
        }

    def _first(self, items: list) -> str | None:
        return items[0] if items else None

    def _founding_year(self, text: str) -> int | None:
        years = YEAR_RE.findall(text)
        return int(min(years)) if years else None

    def _extract_services(self, soup: BeautifulSoup) -> list[str]:
        services: list[str] = []
        for tag in soup.find_all(["li", "h3", "h4"]):
            text = tag.get_text(strip=True)
            if 3 < len(text) < 80:
                services.append(text)
        return list(dict.fromkeys(services))[:10]  # dedupe, cap at 10

    def _extract_people(self, soup: BeautifulSoup) -> list[str]:
        people: list[str] = []
        for tag in soup.find_all(["h3", "h4", "strong"]):
            text = tag.get_text(strip=True)
            # rough heuristic: 2-4 words, title-cased
            words = text.split()
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                people.append(text)
        return list(dict.fromkeys(people))[:5]

    def _detect_language(self, text: str) -> str:
        arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
        ratio = arabic_chars / max(len(text), 1)
        if ratio > 0.3:
            return "ar"
        if ratio > 0.05:
            return "both"
        return "en"
