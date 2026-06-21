import json

from groq import AsyncGroq

from app.core.config import settings
from app.core.llm import groq_chat
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, StoreCandidate

# Intentional deviation from spec: spec calls for Claude vision (image analysis).
# Replaced with Groq text-only analysis of store categories, reviews, and website
# signals — free tier, no image API cost. Vision scoring is approximated from
# text signals rather than actual storefront images.

_SYSTEM_PROMPT = """\
You are a wholesale distribution analyst assessing aesthetic fit between a retail store and a brand.
You have no images — infer the store's vibe from its name, categories, and customer reviews.

Respond with ONLY a valid JSON object, no markdown:
{
  "vibe_score": <float 0.0-10.0>,
  "reasoning": "<1-2 sentences>",
  "matching_signals": ["<text signal that aligned>"],
  "mismatching_signals": ["<text signal that clashed>"]
}

Scoring guide:
9.0-10.0 = Brand would look completely native on their shelves
7.0-8.9  = Strong aesthetic match
5.0-6.9  = Moderate match
3.0-4.9  = Weak match, likely aesthetic clash
0.0-2.9  = No match
"""


async def score_visual_vibe(store: StoreCandidate, brand: BrandProfile) -> DimensionScore:
    store_description = (
        f"Store name: {store.name}\n"
        f"Location: {store.city}, {store.state}\n"
        f"Categories: {', '.join(store.google_categories)}\n"
        f"Price tier: {store.price_tier or 'unknown'}\n"
        f"Customer reviews: {' | '.join(store.review_snippets[:3])}\n"
    )

    brand_description = (
        f"Brand: {brand.brand_name}\n"
        f"Aesthetic keywords: {', '.join(brand.aesthetic_keywords)}\n"
        f"Brand voice: {brand.brand_voice_description}\n"
        f"Primary colors: {', '.join(brand.primary_colors)}\n"
    )

    prompt = (
        f"BRAND PROFILE:\n{brand_description}\n"
        f"STORE PROFILE:\n{store_description}\n"
        "Assess the aesthetic vibe match and respond with JSON only."
    )

    try:
        response = await groq_chat(
            AsyncGroq,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            model=settings.groq_model,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=300,
        )
    except Exception as exc:
        logger.warning("vision_scorer_groq_failed", store=store.name, error=str(exc))
        return DimensionScore(
            score=5.0,
            reasoning="Vibe scoring failed — defaulted to neutral score.",
            data_used=[],
        )

    assert response.usage is not None
    logger.info(
        "groq_token_usage",
        node="vision_scorer",
        model=settings.groq_model,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )

    try:
        parsed = json.loads(response.choices[0].message.content or "")
        score = float(parsed.get("vibe_score", 5.0))
        score = max(0.0, min(10.0, score))
        return DimensionScore(
            score=round(score, 2),
            reasoning=parsed.get("reasoning", ""),
            data_used=parsed.get("matching_signals", []),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("vision_scorer_parse_failed", store=store.name, error=str(exc))
        return DimensionScore(
            score=5.0,
            reasoning="Could not parse vibe score — defaulted to neutral.",
            data_used=[],
        )
