"""Tests for the Scout Agent (app/agents/scout_agent.py)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import BrandExtractionError
from app.models.brand_profile import BrandProfile
from app.services.scout_service import scout_stores

# ---------------------------------------------------------------------------
# Patch targets — must match the import location inside scout_agent.py
# ---------------------------------------------------------------------------

_SEARCH_PLACES = "app.agents.scout_agent.search_places"
_GET_DETAILS = "app.agents.scout_agent.get_place_details"
_GROQ_CLIENT = "app.agents.scout_agent.AsyncGroq"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_BRAND_PROFILE = BrandProfile(
    brand_name="Bloom & Co",
    tagline="Nature-inspired beauty",
    primary_colors=["#F5E6D3", "#2C4A2E"],
    aesthetic_keywords=["botanical", "minimal", "earthy", "clean beauty"],
    product_categories=["skincare", "candles", "body care"],
    price_range=(18.0, 85.0),
    brand_voice_description="Warm and grounded. Speaks to the eco-conscious consumer.",
    wholesale_readiness_score=7.5,
    raw_product_images=["https://cdn.shopify.com/img1.jpg"],
    embedding_vector=[0.1] * 384,
)

_FAKE_QUERIES_RESPONSE = json.dumps({
    "queries": [
        "aesthetic skincare boutique Brooklyn",
        "clean beauty indie shop NYC",
        "botanical wellness store Park Slope",
    ]
})

_FAKE_PLACE_BASE = {
    "place_id": "ChIJplace001",
    "name": "Botanica Beauty Bar",
    "formatted_address": "123 Main St, Brooklyn, NY 11201",
    "types": ["beauty_salon", "establishment"],
    "rating": 4.5,
    "user_ratings_total": 87,
}

_FAKE_DETAILS = {
    "website": "https://botanicabeautybar.com",
    "formatted_phone_number": "(718) 555-0101",
    "opening_hours": {"open_now": True},
    "business_status": "OPERATIONAL",
}


def _make_groq_mock(queries_json: str = _FAKE_QUERIES_RESPONSE) -> MagicMock:
    """Return a mock AsyncGroq client that returns the given JSON for query generation."""
    usage = MagicMock()
    usage.prompt_tokens = 300
    usage.completion_tokens = 100

    choice = MagicMock()
    choice.message.content = queries_json

    completion = MagicMock()
    completion.usage = usage
    completion.choices = [choice]

    async_create = AsyncMock(return_value=completion)

    mock_client = MagicMock()
    mock_client.chat.completions.create = async_create

    MockGroq = MagicMock(return_value=mock_client)
    return MockGroq


def _make_place(place_id: str, name: str, rating: float = 4.2) -> dict:
    return {
        "place_id": place_id,
        "name": name,
        "formatted_address": "456 Fake St, Brooklyn, NY 11201",
        "types": ["store", "establishment"],
        "rating": rating,
        "user_ratings_total": 30,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path():
    """Mock 3 queries × 5 places each. Assert discovered_stores ≥ 1 and all have google_place_id."""
    places_per_query = [
        _make_place(f"ChIJplace{i:03d}", f"Indie Boutique {i}", rating=4.0 + i * 0.1)
        for i in range(5)
    ]

    with (
        patch(_GROQ_CLIENT, new=_make_groq_mock()),
        patch(_SEARCH_PLACES, new=AsyncMock(return_value=places_per_query)),
        patch(_GET_DETAILS, new=AsyncMock(return_value=_FAKE_DETAILS)),
    ):
        result, errors = await scout_stores(
            brand_profile=_FAKE_BRAND_PROFILE,
            vertical_tag="aesthetic_beauty",
            target_location="Brooklyn, NY",
            max_stores=50,
        )

    assert len(result) >= 1
    assert errors == []
    for store in result:
        assert store["google_place_id"], "Every store must have a google_place_id"
        assert "name" in store
        assert "address" in store
        assert "vibe_score" in store
        assert store["status"] == "new"


@pytest.mark.asyncio
async def test_chain_filter():
    """Sephora and Ulta in raw_places must be removed from discovered_stores."""
    chain_places = [
        _make_place("ChIJsephora001", "Sephora"),
        _make_place("ChIJulta001", "Ulta Beauty"),
        _make_place("ChIJindie001", "Indie Glow Studio"),
    ]

    with (
        patch(_GROQ_CLIENT, new=_make_groq_mock()),
        patch(_SEARCH_PLACES, new=AsyncMock(return_value=chain_places)),
        patch(_GET_DETAILS, new=AsyncMock(return_value=_FAKE_DETAILS)),
    ):
        result, errors = await scout_stores(
            brand_profile=_FAKE_BRAND_PROFILE,
            vertical_tag="aesthetic_beauty",
            target_location="Brooklyn, NY",
        )

    names = [s["name"] for s in result]
    assert "Sephora" not in names, "Sephora must be filtered out"
    assert "Ulta Beauty" not in names, "Ulta must be filtered out"
    assert "Indie Glow Studio" in names, "Indie boutique must be kept"


@pytest.mark.asyncio
async def test_invalid_location():
    """Empty target_location should result in discovered_stores being []."""
    result, errors = await scout_stores(
        brand_profile=_FAKE_BRAND_PROFILE,
        vertical_tag="aesthetic_beauty",
        target_location="",
    )

    assert result == [], f"Expected empty list, got: {result}"


@pytest.mark.asyncio
async def test_maps_api_failure():
    """search_places raising BrandExtractionError → discovered_stores is [] and errors non-empty."""
    with (
        patch(_GROQ_CLIENT, new=_make_groq_mock()),
        patch(
            _SEARCH_PLACES,
            new=AsyncMock(
                side_effect=BrandExtractionError(
                    message="Google Maps API error: status=REQUEST_DENIED",
                    retry_suggestion="Check your API key.",
                )
            ),
        ),
    ):
        result, errors = await scout_stores(
            brand_profile=_FAKE_BRAND_PROFILE,
            vertical_tag="aesthetic_beauty",
            target_location="Brooklyn, NY",
        )

    assert result == [], f"Expected [], got {result}"
    assert any("Google Maps" in e or "REQUEST_DENIED" in e for e in errors), (
        f"Expected Google Maps error in errors, got: {errors}"
    )


@pytest.mark.asyncio
async def test_no_results():
    """search_places returning [] for all queries → discovered_stores is []."""
    with (
        patch(_GROQ_CLIENT, new=_make_groq_mock()),
        patch(_SEARCH_PLACES, new=AsyncMock(return_value=[])),
    ):
        result, errors = await scout_stores(
            brand_profile=_FAKE_BRAND_PROFILE,
            vertical_tag="aesthetic_beauty",
            target_location="Brooklyn, NY",
        )

    assert result == [], f"Expected [] when no places found, got {result}"


@pytest.mark.asyncio
async def test_deduplication():
    """Same place_id returned by multiple queries must appear only once in discovered_stores."""
    # All three queries return the same place
    duplicate_place = _make_place("ChIJduplicate001", "The Shared Boutique")

    call_count = 0

    async def search_side_effect(query: str, location: str, api_key: str) -> list[dict]:
        nonlocal call_count
        call_count += 1
        return [duplicate_place]

    with (
        patch(_GROQ_CLIENT, new=_make_groq_mock()),
        patch(_SEARCH_PLACES, new=AsyncMock(side_effect=search_side_effect)),
        patch(_GET_DETAILS, new=AsyncMock(return_value=_FAKE_DETAILS)),
    ):
        result, errors = await scout_stores(
            brand_profile=_FAKE_BRAND_PROFILE,
            vertical_tag="aesthetic_beauty",
            target_location="Brooklyn, NY",
        )

    place_ids = [s["google_place_id"] for s in result]
    assert place_ids.count("ChIJduplicate001") == 1, (
        f"Duplicate place_id appeared {place_ids.count('ChIJduplicate001')} times, expected 1"
    )
    # Confirm all 3 queries were actually called
    assert call_count == 3, f"Expected 3 search calls, got {call_count}"
