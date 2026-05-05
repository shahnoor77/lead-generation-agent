"""
Shared LLM client with retry logic for Ollama.

When the server is under load, Ollama returns 503 or times out.
This module wraps the OpenAI client with:
  - Long timeout (300s) — model may be queued, not dead
  - Automatic retries with exponential backoff (up to 3 attempts)
  - Jitter to avoid thundering herd when multiple leads retry simultaneously
  - Consistent logging across all LLM calls

Usage:
    from app.utils.llm_client import llm_chat

    response = await llm_chat(
        model=settings.ollama_model,
        messages=[...],
        max_tokens=300,
        temperature=0.2,
    )
    text = response.choices[0].message.content or ""
"""

from __future__ import annotations
import asyncio
import random
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Single shared client — long timeout because Ollama queues requests under load
_client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=300.0,   # 5 minutes — covers queued requests on a busy server
)

_MAX_RETRIES = 3
_BASE_DELAY  = 5.0   # seconds before first retry
_MAX_DELAY   = 30.0  # cap on backoff


async def llm_chat(
    model: str,
    messages: list[dict],
    max_tokens: int = 300,
    temperature: float = 0.2,
    **kwargs,
):
    """
    Call Ollama with automatic retry on timeout / server overload.

    Retries on:
      - APITimeoutError   (request timed out)
      - APIConnectionError (connection refused / reset)
      - APIStatusError 503 (server busy / model loading)

    Does NOT retry on:
      - 4xx errors (bad request — retrying won't help)
      - Successful responses with bad content (caller handles that)
    """
    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await _client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            if attempt > 1:
                logger.info("llm_client.retry_succeeded", attempt=attempt, model=model)
            return response

        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            logger.warning(
                "llm_client.timeout_or_connection",
                attempt=attempt,
                max_retries=_MAX_RETRIES,
                model=model,
                error=str(e)[:120],
            )

        except APIStatusError as e:
            if e.status_code == 503:
                last_error = e
                logger.warning(
                    "llm_client.server_busy",
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    model=model,
                    status=e.status_code,
                )
            else:
                # Non-retryable (400, 401, 404, etc.)
                logger.error("llm_client.non_retryable_error", status=e.status_code, model=model)
                raise

        except Exception as e:
            # Unknown error — don't retry
            logger.error("llm_client.unexpected_error", model=model, error=str(e)[:200])
            raise

        # Exponential backoff with jitter before next attempt
        if attempt < _MAX_RETRIES:
            delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
            jitter = random.uniform(0, delay * 0.3)
            wait = delay + jitter
            logger.info("llm_client.retrying", attempt=attempt, wait_seconds=round(wait, 1), model=model)
            await asyncio.sleep(wait)

    # All retries exhausted
    logger.error("llm_client.all_retries_failed", attempts=_MAX_RETRIES, model=model)
    raise last_error or RuntimeError(f"LLM call failed after {_MAX_RETRIES} attempts")
