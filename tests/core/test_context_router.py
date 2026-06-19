"""Context Router resolution + prompt-injection into scout and brand-analyzer calls."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.context_router import list_verticals, resolve_vertical
from app.models.brand_profile import BrandProfile

# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def test_canonical_tag_resolves() -> None:
    assert resolve_vertical("aesthetic_beauty").tag == "aesthetic_beauty"


def test_alias_resolves() -> None:
    assert resolve_vertical("beauty").tag == "aesthetic_beauty"
    assert resolve_vertical("skincare").tag == "aesthetic_beauty"
    assert resolve_vertical("apparel").tag == "fashion"


def test_resolution_is_format_insensitive() -> None:
    for variant in ("Aesthetic-Beauty", " BEAUTY ", "clean beauty", "clean_beauty"):
        assert resolve_vertical(variant).tag == "aesthetic_beauty"


def test_unknown_and_empty_fall_back_to_default() -> None:
    assert resolve_vertical("crypto_widgets").tag == "default"
    assert resolve_vertical("").tag == "default"
    assert resolve_vertical(None).tag == "default"


def test_list_verticals_has_known_tags() -> None:
    tags = set(list_verticals())
    assert {"aesthetic_beauty", "fashion", "wellness", "home_goods", "food_beverage"} <= tags


# ---------------------------------------------------------------------------
# prompt addenda
# ---------------------------------------------------------------------------


def test_extraction_addendum_carries_niche_signals() -> None:
    text = resolve_vertical("beauty").extraction_prompt_addendum()
    assert "Leaping Bunny" in text
    assert "aesthetic beauty" in text


def test_scouting_addendum_carries_store_types() -> None:
    text = resolve_vertical("beauty").scouting_prompt_addendum()
    assert "medical spas" in text


def test_default_profile_has_empty_addenda() -> None:
    default = resolve_vertical("unknown")
    assert default.scouting_prompt_addendum() == ""
    assert default.extraction_prompt_addendum() == ""


# ---------------------------------------------------------------------------
# injection into the live LLM call sites
# ---------------------------------------------------------------------------


def _fake_groq(capture: dict, content: str) -> MagicMock:
    client = MagicMock()

    async def _create(**kwargs: Any) -> MagicMock:
        capture["messages"] = kwargs["messages"]
        resp = MagicMock()
        resp.usage.prompt_tokens = 10
        resp.usage.completion_tokens = 5
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    client.chat.completions.create = _create
    return client


@pytest.mark.asyncio
async def test_scout_query_prompt_includes_vertical_guidance() -> None:
    from app.agents.scout_agent import generate_queries_node

    brand = BrandProfile(
        brand_name="SkinGlow",
        tagline="",
        primary_colors=[],
        aesthetic_keywords=["clean"],
        product_categories=["skincare"],
        price_range=(25.0, 150.0),
        brand_voice_description="",
        wholesale_readiness_score=8.0,
        raw_product_images=[],
        embedding_vector=[0.1] * 8,
    )
    state = {
        "brand_profile": brand,
        "vertical_tag": "beauty",
        "target_location": "Brooklyn, NY",
        "errors": [],
    }
    capture: dict = {}
    fake = _fake_groq(capture, json.dumps({"queries": ["clean beauty boutique Brooklyn"]}))

    with patch("app.agents.scout_agent.AsyncGroq", return_value=fake):
        result = await generate_queries_node(state)  # type: ignore[arg-type]

    assert result["search_queries"]
    user_msg = capture["messages"][1]["content"]
    assert "medical spas" in user_msg  # vertical store-type guidance injected


@pytest.mark.asyncio
async def test_brand_analyzer_prompt_includes_niche_signals() -> None:
    from app.tools.vision_analyzer import analyze_brand_aesthetics

    capture: dict = {}
    fake = _fake_groq(capture, json.dumps({"brand_name": "SkinGlow"}))

    with patch("app.tools.vision_analyzer.AsyncGroq", return_value=fake):
        analysis, _usage = await analyze_brand_aesthetics(
            about_text="A clean skincare brand.",
            products=[],
            vertical_tag="beauty",
        )

    assert analysis["brand_name"] == "SkinGlow"
    user_msg = capture["messages"][1]["content"]
    assert "Leaping Bunny" in user_msg  # niche extraction guidance injected
