"""
LLM-based website summarizer with output quality validation.
Uses Ollama (local) via the OpenAI-compatible /v1 endpoint.
Model: qwen2.5:14b

Validation runs after every LLM call.
Falls back to a safe placeholder if output fails quality checks.
"""

from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger
from app.utils.prompt_loader import load_prompt
from app.modules.quality.output_quality_validator import (
    validate_summary,
    summary_fallback,
)

logger = get_logger(__name__)

client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=30.0,   # fail fast — fallback handles timeouts gracefully
)

# Metadata tag appended to fallback summaries so operators can identify them
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
            response = await client.chat.completions.create(
                model=settings.ollama_summarize_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.2,
            )
            summary = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("summarizer.llm_failed", company=company_name, error=str(e))
            return summary_fallback(company_name, category, location) + _FALLBACK_TAG

        # Validate quality
        result = validate_summary(summary, company_name)
        if not result.passed:
            logger.warning(
                "summarizer.quality_failed",
                company=company_name,
                issues=result.issues,
            )
            return summary_fallback(company_name, category, location) + _FALLBACK_TAG

        logger.debug("enrichment.summarized", company=company_name, chars=len(summary))
        return summary
