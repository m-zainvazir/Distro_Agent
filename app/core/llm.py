"""Multi-provider LLM failover (Blueprint Layer 18).

Wraps a Groq chat-completion call so that, when a fallback provider is
configured, transient failures (rate limits, 5xx, connection/timeout) fail over
to it instead of breaking the pipeline. When no fallback is configured the chain
is a single provider and behaviour is identical to calling Groq directly.

The caller passes its own ``AsyncGroq`` class in (``groq_chat(AsyncGroq, ...)``)
so the failover boundary is the caller's module-level symbol — keeping existing
``patch("app.agents.x.AsyncGroq")`` test seams intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import logger

# Error type names / HTTP statuses worth failing over on.
_RETRYABLE_NAMES = {
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "APIError",
}


@dataclass(frozen=True)
class _Provider:
    name: str
    api_key: str
    model: str


def _provider_chain(model: str) -> list[_Provider]:
    """Primary provider, plus a fallback if a fallback key or model is configured."""
    chain = [_Provider("groq_primary", settings.groq_api_key, model)]

    fb_key = settings.groq_api_key_fallback
    fb_model = settings.groq_model_fallback
    if fb_key or fb_model:
        chain.append(
            _Provider(
                "groq_fallback",
                fb_key or settings.groq_api_key,
                fb_model or model,
            )
        )
    return chain


def _is_retryable(exc: Exception) -> bool:
    """True for rate-limit / 5xx / connection-style errors worth failing over on."""
    if type(exc).__name__ in _RETRYABLE_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


async def groq_chat(
    groq_cls: Any,
    *,
    messages: list[dict],
    model: str,
    **create_kwargs: Any,
) -> Any:
    """Call Groq chat completion with provider failover; return the raw response.

    Args:
        groq_cls: the AsyncGroq class to instantiate (passed in so test patches
            on the caller's module symbol remain effective).
        messages: chat messages.
        model: primary model id.
        **create_kwargs: forwarded to ``chat.completions.create`` (response_format,
            max_tokens, temperature, ...).
    """
    chain = _provider_chain(model)
    last_idx = len(chain) - 1

    for i, provider in enumerate(chain):
        try:
            client = groq_cls(api_key=provider.api_key)
            response = await client.chat.completions.create(
                model=provider.model,
                messages=messages,
                **create_kwargs,
            )
            if i > 0:
                logger.info("llm_failover_succeeded", provider=provider.name, attempt=i + 1)
            return response
        except Exception as exc:
            if i < last_idx and _is_retryable(exc):
                logger.warning(
                    "llm_provider_failover",
                    failed_provider=provider.name,
                    error=str(exc)[:160],
                )
                continue
            raise
