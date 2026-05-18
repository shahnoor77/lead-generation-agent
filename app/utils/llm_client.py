"""
Shared LLM client with retry logic and user-configurable model override.

Priority:
  1. Explicit model= argument (caller override)
  2. User's saved ai_model setting (if user_id provided)
  3. settings.ollama_model (system default)

Retry logic:
  - 300s timeout (Ollama queues requests under load)
  - 3 retries with exponential backoff + jitter
  - Retries on: timeout, connection error, 503
  - Does NOT retry on 4xx
"""

from __future__ import annotations
import asyncio
import random
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",
    timeout=300.0,
)

_MAX_RETRIES = 3
_BASE_DELAY  = 5.0
_MAX_DELAY   = 30.0


async def _resolve_model(model: str | None, user_id: str | None) -> str:
    """
    Resolve which model to use.
    Priority: explicit model arg > user setting > system default.
    """
    if model:
        return model

    if user_id is not None:
        try:
            from app.services.settings import get_settings
            user_settings = await get_settings(user_id)
            user_model = user_settings.ai_agent.model.strip()
            if user_model:
                logger.debug("llm_client.user_model", user_id=user_id, model=user_model)
                return user_model
        except Exception:
            pass  # fall through to default

    return settings.ollama_model


async def llm_chat(
    model: str | None = None,
    messages: list[dict] = None,
    max_tokens: int = 300,
    temperature: float = 0.2,
    user_id: str | None = None,
    **kwargs,
):
    """
    Call Ollama with automatic retry on timeout / server overload.

    Args:
        model:       Explicit model override. If None, uses user setting or system default.
        messages:    Chat messages list.
        max_tokens:  Max tokens to generate.
        temperature: Sampling temperature.
        user_id:     If provided, loads user's configured model from settings.
    """
    if messages is None:
        messages = []

    resolved_model = await _resolve_model(model, user_id)
    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await _client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            if attempt > 1:
                logger.info("llm_client.retry_succeeded", attempt=attempt, model=resolved_model)
            return response

        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            logger.warning("llm_client.timeout_or_connection",
                           attempt=attempt, max_retries=_MAX_RETRIES,
                           model=resolved_model, error=str(e)[:120])

        except APIStatusError as e:
            if e.status_code == 503:
                last_error = e
                logger.warning("llm_client.server_busy",
                               attempt=attempt, max_retries=_MAX_RETRIES,
                               model=resolved_model, status=e.status_code)
            else:
                logger.error("llm_client.non_retryable_error",
                             status=e.status_code, model=resolved_model)
                raise

        except Exception as e:
            logger.error("llm_client.unexpected_error",
                         model=resolved_model, error=str(e)[:200])
            raise

        if attempt < _MAX_RETRIES:
            delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
            wait = delay + random.uniform(0, delay * 0.3)
            logger.info("llm_client.retrying",
                        attempt=attempt, wait_seconds=round(wait, 1), model=resolved_model)
            await asyncio.sleep(wait)

    logger.error("llm_client.all_retries_failed",
                 attempts=_MAX_RETRIES, model=resolved_model)
    raise last_error or RuntimeError(f"LLM call failed after {_MAX_RETRIES} attempts")
