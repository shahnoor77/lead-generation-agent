"""
LLM-based website summarizer.
Uses Ollama (local) via the OpenAI-compatible /v1 endpoint.
Model: qwen2.5:14b — good at summarization, lighter than the coder variant.
"""

from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger
from app.utils.prompt_loader import load_prompt

logger = get_logger(__name__)

# OpenAI client pointed at Ollama's OpenAI-compatible endpoint.
# api_key is required by the client lib but ignored by Ollama.
client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=120.0,
)


class WebsiteSummarizer:
    async def summarize(self, company_name: str, raw_text: str) -> str:
        if not raw_text.strip():
            return ""

        prompt = load_prompt("enrichment_summarize").format(
            company_name=company_name,
            website_text=raw_text[:3000],
        )

        response = await client.chat.completions.create(
            model=settings.ollama_summarize_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.2,
        )

        summary = response.choices[0].message.content or ""
        logger.debug("enrichment.summarized", company=company_name, chars=len(summary))
        return summary.strip()
