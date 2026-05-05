"""
LLM-based website summarizer with output quality validation.
Uses shared LLM client with retry logic.
Model: qwen2.5:1.5b — fast (2-5s), sufficient for 2-3 sentence summaries.
"""

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.prompt_loader import load_prompt
from app.utils.llm_client import llm_chat
from app.modules.quality.output_quality_validator import (
    validate_summary,
    summary_fallback,
)

logger = get_logger(__name__)

_FALLBACK_TAG = " [auto-fallback]"


class WebsiteSummarizer:
    async def summarize(
        self,
        company_name: str,
        raw_text: str,
        category: str | None = None,
        location: str | None = None,
    ) -> str:
        if not raw_text.strip():
            logger.info("summarizer.skipped", company=company_name, reason="empty_text")
            return summary_fallback(company_name, category, location) + _FALLBACK_TAG

        prompt = load_prompt("enrichment_summarize").format(
            company_name=company_name,
            website_text=raw_text[:3000],
        )

        try:
            response = await llm_chat(
                model=settings.ollama_summarize_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.2,
            )
            summary = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("summarizer.llm_failed", company=company_name, error=str(e)[:120])
            return summary_fallback(company_name, category, location) + _FALLBACK_TAG

        result = validate_summary(summary, company_name)
        if not result.passed:
            logger.warning("summarizer.quality_failed", company=company_name, issues=result.issues)
            return summary_fallback(company_name, category, location) + _FALLBACK_TAG

        logger.debug("enrichment.summarized", company=company_name, chars=len(summary))
        return summary
