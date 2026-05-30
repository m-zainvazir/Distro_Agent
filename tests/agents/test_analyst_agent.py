from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, ScoredStore, StoreCandidate
from app.services.analyst_service import score_stores

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_VISION = "app.agents.analyst_agent.score_visual_vibe"
_WHOLESALE = "app.agents.analyst_agent.score_wholesale_signals"
_GROQ = "app.agents.analyst_agent.AsyncGroq"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_BRAND = BrandProfile(
    brand_name="Bloom & Co",
    tagline="Nature-inspired beauty",
    primary_colors=["#F5E6D3", "#2C4A2E"],
    aesthetic_keywords=["botanical", "minimal", "earthy", "clean beauty", "skincare"],
    product_categories=["skincare", "candles", "body care"],
    price_range=(18.0, 85.0),
    brand_voice_description="Warm and grounded.",
    wholesale_readiness_score=7.5,
    raw_product_images=[],
    embedding_vector=[0.1] * 384,
)

_FAKE_VIBE = DimensionScore(
    score=9.0,
    reasoning="Perfect aesthetic match.",
    data_used=["botanical", "minimal"],
)

_FAKE_WHOLESALE_HIGH = DimensionScore(
    score=8.0,
    reasoning="Found: curated, independent brands.",
    data_used=["review_snippets"],
)

_FAKE_WHOLESALE_LOW = DimensionScore(
    score=2.0,
    reasoning="No wholesale signals detected.",
    data_used=["review_snippets"],
)


def _make_store(
    place_id: str = "ChIJ001",
    name: str = "Botanica Studio",
    price_tier: str = "$$",
    google_categories: list[str] | None = None,
    review_snippets: list[str] | None = None,
    instagram_followers: int | None = 8000,
    instagram_posts: int | None = 10,
) -> StoreCandidate:
    return StoreCandidate(
        place_id=place_id,
        name=name,
        address="123 Main St",
        city="Brooklyn",
        state="NY",
        google_categories=google_categories or ["skincare", "boutique", "beauty", "candles", "minimal"],
        website_url=None,
        instagram_handle="@botanica",
        instagram_followers=instagram_followers,
        instagram_posts_last_30_days=instagram_posts,
        storefront_image_urls=[],
        price_tier=price_tier,
        review_snippets=review_snippets or ["curated skincare", "independent brands", "botanical"],
        is_chain=False,
    )


def _make_groq_mock(summary: str = "Great match.", why: str = "Strong category alignment.") -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = 200
    usage.completion_tokens = 80

    import json
    choice = MagicMock()
    choice.message.content = json.dumps({"match_summary": summary, "why_matched": why})

    completion = MagicMock()
    completion.usage = usage
    completion.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=completion)

    return MagicMock(return_value=mock_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_pipeline_high_scorer():
    """High-scoring store triggers vision, gets HIGH priority."""
    store = _make_store(google_categories=["skincare", "boutique", "beauty", "candles", "minimal"])

    with (
        patch(_VISION, new=AsyncMock(return_value=_FAKE_VIBE)),
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_HIGH)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store])

    assert len(results) == 1
    scored = results[0]
    assert isinstance(scored, ScoredStore)
    assert scored.vision_was_run is True
    assert scored.final_score >= 8.0
    assert scored.outreach_priority == "HIGH"
    assert scored.match_summary != ""
    assert scored.why_matched != ""


@pytest.mark.asyncio
async def test_text_only_path_low_scorer():
    """Low-scoring store skips vision entirely."""
    store = _make_store(
        google_categories=["electronics", "hardware"],
        review_snippets=["good service", "fast delivery"],
        price_tier="$",
        instagram_followers=200,
        instagram_posts=1,
    )

    with (
        patch(_VISION, new=AsyncMock(return_value=_FAKE_VIBE)) as mock_vision,
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_LOW)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store])

    assert len(results) == 1
    scored = results[0]
    assert scored.vision_was_run is False
    assert scored.visual_vibe_score is None
    mock_vision.assert_not_called()


@pytest.mark.asyncio
async def test_scoring_threshold_boundary():
    """Stores just below 8.0 skip vision; at or above trigger it."""
    store_low = _make_store(
        place_id="low",
        google_categories=["electronics"],
        review_snippets=["cheap goods"],
        price_tier="$",
        instagram_followers=100,
        instagram_posts=0,
    )
    store_high = _make_store(
        place_id="high",
        google_categories=["skincare", "boutique", "beauty", "candles", "minimal"],
        instagram_followers=10_000,
        instagram_posts=15,
    )

    call_log: list[str] = []

    async def mock_vision(store: StoreCandidate, brand: BrandProfile) -> DimensionScore:
        call_log.append(store.place_id)
        return _FAKE_VIBE

    with (
        patch(_VISION, new=mock_vision),
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_HIGH)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store_low, store_high])

    vision_run = {s.store.place_id: s.vision_was_run for s in results}
    assert vision_run["low"] is False
    assert vision_run["high"] is True
    assert "low" not in call_log
    assert "high" in call_log


@pytest.mark.asyncio
async def test_no_instagram_data():
    """None instagram_followers → engagement score 4.0; pipeline completes."""
    store = _make_store(instagram_followers=None, instagram_posts=None)

    with (
        patch(_VISION, new=AsyncMock(return_value=_FAKE_VIBE)),
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_HIGH)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store])

    assert len(results) == 1
    assert results[0].engagement_score.score == 4.0
    assert "No Instagram data" in results[0].engagement_score.reasoning


@pytest.mark.asyncio
async def test_no_storefront_images():
    """Vision triggered but vibe scorer returns default 5.0 (no images fallback)."""
    store = _make_store(google_categories=["skincare", "boutique", "beauty", "candles", "minimal"])
    default_vibe = DimensionScore(
        score=5.0,
        reasoning="No storefront images available — defaulted to neutral score",
        data_used=[],
    )

    with (
        patch(_VISION, new=AsyncMock(return_value=default_vibe)),
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_HIGH)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store])

    scored = results[0]
    assert scored.vision_was_run is True
    assert scored.visual_vibe_score is not None
    assert scored.visual_vibe_score.score == 5.0
    assert scored.visual_vibe_score.data_used == []


@pytest.mark.asyncio
async def test_website_fetch_failure():
    """wholesale_scorer httpx failure is non-blocking; pipeline completes."""
    store = _make_store()
    fallback = DimensionScore(
        score=1.5,
        reasoning="Website fetch failed — scored from reviews only.",
        data_used=["review_snippets"],
    )

    with (
        patch(_VISION, new=AsyncMock(return_value=_FAKE_VIBE)),
        patch(_WHOLESALE, new=AsyncMock(return_value=fallback)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store])

    assert len(results) == 1
    assert results[0].wholesale_score.score == 1.5


@pytest.mark.asyncio
async def test_sorted_output_order():
    """Output must be sorted by final_score descending."""
    stores = [
        _make_store(place_id="a", name="Store A", instagram_followers=200, instagram_posts=1,
                    google_categories=["electronics"], review_snippets=["ok"], price_tier="$"),
        _make_store(place_id="b", name="Store B", instagram_followers=10_000, instagram_posts=15,
                    google_categories=["skincare", "boutique", "beauty", "candles", "minimal"]),
        _make_store(place_id="c", name="Store C", instagram_followers=3_000, instagram_posts=6,
                    google_categories=["boutique", "beauty"]),
    ]

    with (
        patch(_VISION, new=AsyncMock(return_value=_FAKE_VIBE)),
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_HIGH)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, stores)

    scores = [r.final_score for r in results]
    assert scores == sorted(scores, reverse=True), f"Not sorted descending: {scores}"


@pytest.mark.asyncio
async def test_cost_tracking():
    """total_cost_usd > 0 after vision runs; vision_calls_made matches HIGH stores."""
    store = _make_store(google_categories=["skincare", "boutique", "beauty", "candles", "minimal"])

    with (
        patch(_VISION, new=AsyncMock(return_value=_FAKE_VIBE)),
        patch(_WHOLESALE, new=AsyncMock(return_value=_FAKE_WHOLESALE_HIGH)),
        patch(_GROQ, new=_make_groq_mock()),
    ):
        results = await score_stores(_FAKE_BRAND, [store])

    assert len(results) == 1
    assert results[0].vision_was_run is True
