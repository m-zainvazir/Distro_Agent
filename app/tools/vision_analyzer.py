import json

from groq import AsyncGroq

from app.core.config import settings
from app.core.logging import logger

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


async def analyze_brand_aesthetics(
    about_text: str,
    products: list[dict],
    vertical_tag: str,
) -> tuple[dict, dict[str, int]]:
    """Call Groq (text-only) and return (analysis_dict, token_usage)."""
    client = AsyncGroq(api_key=settings.groq_api_key)

    product_summary = "\n".join(
        f"- {p.get('title', '')} | price: {p.get('price', p.get('variants', [{}])[0].get('price', 'N/A') if p.get('variants') else 'N/A')}"
        for p in products[:30]
    )
    user_content = (
        f"Vertical: {vertical_tag}\n\n"
        f"About text:\n{about_text[:2000]}\n\n"
        f"Product catalog sample:\n{product_summary}"
    )

    response = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=1024,
    )

    token_usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }
    logger.info(
        "groq_token_usage",
        model=settings.groq_model,
        input_tokens=token_usage["input_tokens"],
        output_tokens=token_usage["output_tokens"],
    )

    analysis: dict = json.loads(response.choices[0].message.content)
    return analysis, token_usage
