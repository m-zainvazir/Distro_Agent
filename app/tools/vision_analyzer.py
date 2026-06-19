from __future__ import annotations

import asyncio
import json

from groq import AsyncGroq

from app.core.budget import LeadBudget
from app.core.config import settings
from app.core.logging import logger

_MAX_ATTEMPTS = 3

_SYSTEM_PROMPT = """\
You are a brand intelligence analyst. Given product catalog data and brand text, return a JSON object with exactly these keys:
- brand_name (str)
- tagline (str)
- aesthetic_keywords (list of str, e.g. ["minimalist", "botanical"])
- product_categories (list of str)
- price_range_min (float, USD)
- price_range_max (float, USD)
- brand_voice_description (str, 2-3 sentences)
- wholesale_readiness_score (float 0-10)

Respond with ONLY valid JSON. No markdown fences, no explanation.
"""

_NAME_CONSTRAINT = (
    'IMPORTANT: The brand name is EXACTLY "{name}". '
    "Use this name verbatim for brand_name. Do NOT use a product name, sub-brand, or line name."
)

# Groq llama-3.3-70b pricing: $0.59 / $0.79 per 1M tokens
_COST_PER_1K_INPUT = 0.00059
_COST_PER_1K_OUTPUT = 0.00079


async def analyze_brand_aesthetics(
    about_text: str,
    products: list[dict],
    vertical_tag: str,
    canonical_name: str = "",
    budget: LeadBudget | None = None,
) -> tuple[dict, dict[str, int]]:
    """Call Groq (text-only) and return (analysis_dict, token_usage).

    If *budget* is supplied, actual token usage is recorded to the lead ledger
    after each successful call via ``budget.record_usage``.
    """
    client = AsyncGroq(api_key=settings.groq_api_key)

    product_summary = "\n".join(
        f"- {p.get('title', '')} | price: {p.get('price', p.get('variants', [{}])[0].get('price', 'N/A') if p.get('variants') else 'N/A')}"
        for p in products
    )
    name_instruction = (
        f"\n\n{_NAME_CONSTRAINT.format(name=canonical_name)}" if canonical_name else ""
    )
    # Context Router: inject niche-aware extraction guidance for this vertical.
    from app.core.context_router import resolve_vertical

    vertical_guidance = resolve_vertical(vertical_tag).extraction_prompt_addendum()
    user_content = (
        f"Vertical: {vertical_tag}\n\n"
        f"About text:\n{about_text[:2000]}\n\n"
        f"Product catalog sample:\n{product_summary}"
        f"{name_instruction}"
        f"{vertical_guidance}"
    )

    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                max_tokens=1024,
            )
            assert response.usage is not None
            token_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
            analysis: dict = json.loads(response.choices[0].message.content or "")
            logger.info(
                "groq_token_usage",
                model=settings.groq_model,
                input_tokens=token_usage["input_tokens"],
                output_tokens=token_usage["output_tokens"],
            )
            if budget is not None:
                actual_cost = (
                    (token_usage["input_tokens"] / 1000) * _COST_PER_1K_INPUT
                    + (token_usage["output_tokens"] / 1000) * _COST_PER_1K_OUTPUT
                )
                budget.record_usage(
                    tokens=token_usage["input_tokens"] + token_usage["output_tokens"],
                    cost_usd=actual_cost,
                )
            return analysis, token_usage
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "analyze_brand_aesthetics_retry",
                attempt=attempt + 1,
                max_attempts=_MAX_ATTEMPTS,
                error=str(exc),
            )
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.5 * (attempt + 1))

    assert last_exc is not None
    raise last_exc
