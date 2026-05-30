"""
Validation tests for app/workflows/phase1_workflow.py

Covers:
  1. Happy path — all 4 nodes run in sequence, report file created
  2. Report markdown content — brand name, tenant, store count, location
  3. Brand extraction failure — scout and analyst are never called
  4. Scout failure — brand profile preserved, analyst skipped
  5. Error threshold — 4 pre-seeded errors → error_handler short-circuits
  6. Analyst failure — report still written with 0 scored stores
  7. _scout_dict_to_candidate — full address parses city/state correctly
  8. _scout_dict_to_candidate — missing fields default without raising
  9. _scout_dict_to_candidate — 2-part address parses correctly

Patch targets (mock the three services, not the low-level agents):
  - app.workflows.phase1_workflow.extract_brand
  - app.workflows.phase1_workflow.scout_stores
  - app.workflows.phase1_workflow.score_stores

Run:
  pytest app/tests/workflow1_test.py -v
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, ScoredStore, StoreCandidate
from app.workflows.phase1_workflow import _scout_dict_to_candidate, phase1_graph

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_EXTRACT = "app.workflows.phase1_workflow.extract_brand"
_SCOUT   = "app.workflows.phase1_workflow.scout_stores"
_SCORE   = "app.workflows.phase1_workflow.score_stores"

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_FAKE_BRAND = BrandProfile(
    brand_name="Bloom & Co",
    tagline="Nature-inspired beauty",
    primary_colors=["#F5E6D3"],
    aesthetic_keywords=["botanical", "minimal", "earthy"],
    product_categories=["skincare", "candles"],
    price_range=(18.0, 85.0),
    brand_voice_description="Warm and grounded.",
    wholesale_readiness_score=7.5,
    raw_product_images=[],
    embedding_vector=[0.1] * 384,
)

_FAKE_SCOUT_RAW = [
    {
        "google_place_id": "ChIJ001",
        "name": "Botanica Studio",
        "address": "123 Main St, Brooklyn, NY 11201",
        "instagram_handle": "@botanica",
    },
    {
        "google_place_id": "ChIJ002",
        "name": "Green Leaf Boutique",
        "address": "456 Park Ave, Manhattan, NY 10016",
        "instagram_handle": None,
    },
]


def _make_dim(score: float = 7.0) -> DimensionScore:
    return DimensionScore(score=score, reasoning="test", data_used=[])


def _make_scored(store: StoreCandidate, score: float = 8.5) -> ScoredStore:
    dim = _make_dim(score)
    return ScoredStore(
        store=store,
        visual_vibe_score=None,
        category_score=dim,
        price_score=dim,
        engagement_score=dim,
        wholesale_score=dim,
        text_score=score,
        final_score=score,
        vision_was_run=False,
        match_summary="Good match.",
        why_matched="Strong category alignment.",
        outreach_priority="HIGH",
    )


def _base_input() -> dict:
    return {
        "brand_url": "https://example.com",
        "vertical_tag": "beauty",
        "target_location": "Brooklyn, NY",
        "tenant_id": "tenant-123",
        "brand_profile": None,
        "store_candidates": [],
        "scored_stores": [],
        "report_url": "",
        "errors": [],
    }


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_all_nodes_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All 4 nodes run in sequence; report file is created on disk."""
    monkeypatch.chdir(tmp_path)

    candidates = [_scout_dict_to_candidate(r) for r in _FAKE_SCOUT_RAW]
    scored = [_make_scored(c) for c in candidates]

    with (
        patch(_EXTRACT, new=AsyncMock(return_value=_FAKE_BRAND)),
        patch(_SCOUT, new=AsyncMock(return_value=_FAKE_SCOUT_RAW)),
        patch(_SCORE, new=AsyncMock(return_value=scored)),
    ):
        result = await phase1_graph.ainvoke(_base_input())

    assert result["brand_profile"] == _FAKE_BRAND
    assert len(result["store_candidates"]) == 2
    assert len(result["scored_stores"]) == 2
    assert result["report_url"] != ""
    assert result["errors"] == []
    assert Path(result["report_url"]).exists()


# ---------------------------------------------------------------------------
# 2. Report markdown content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_report_markdown_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Report file contains brand name, tenant ID, store count, and location."""
    monkeypatch.chdir(tmp_path)

    candidates = [_scout_dict_to_candidate(_FAKE_SCOUT_RAW[0])]
    scored = [_make_scored(candidates[0])]

    with (
        patch(_EXTRACT, new=AsyncMock(return_value=_FAKE_BRAND)),
        patch(_SCOUT, new=AsyncMock(return_value=_FAKE_SCOUT_RAW[:1])),
        patch(_SCORE, new=AsyncMock(return_value=scored)),
    ):
        result = await phase1_graph.ainvoke(_base_input())

    content = Path(result["report_url"]).read_text(encoding="utf-8")
    assert "Bloom & Co" in content
    assert "tenant-123" in content
    assert "1 stores scored" in content
    assert "Brooklyn, NY" in content


# ---------------------------------------------------------------------------
# 3. Brand extraction failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brand_failure_skips_scout_and_analyst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brand extraction failure → scout and analyst are never invoked."""
    from app.core.errors import BrandExtractionError

    monkeypatch.chdir(tmp_path)
    mock_scout = AsyncMock(return_value=_FAKE_SCOUT_RAW)
    mock_score = AsyncMock(return_value=[])

    with (
        patch(_EXTRACT, new=AsyncMock(side_effect=BrandExtractionError("no data"))),
        patch(_SCOUT, new=mock_scout),
        patch(_SCORE, new=mock_score),
    ):
        result = await phase1_graph.ainvoke(_base_input())

    assert result["brand_profile"] is None
    assert result["store_candidates"] == []
    mock_scout.assert_not_called()
    mock_score.assert_not_called()
    assert any("brand_extractor" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 4. Scout failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scout_failure_skips_analyst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scout failure → brand profile preserved, analyst never called."""
    monkeypatch.chdir(tmp_path)
    mock_score = AsyncMock(return_value=[])

    with (
        patch(_EXTRACT, new=AsyncMock(return_value=_FAKE_BRAND)),
        patch(_SCOUT, new=AsyncMock(side_effect=RuntimeError("Maps API down"))),
        patch(_SCORE, new=mock_score),
    ):
        result = await phase1_graph.ainvoke(_base_input())

    assert result["brand_profile"] == _FAKE_BRAND
    assert result["store_candidates"] == []
    mock_score.assert_not_called()
    assert any("scout" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 5. Error threshold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_threshold_routes_to_error_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4 pre-seeded errors exceed _ERROR_THRESHOLD=3 → error_handler fires, scout never called."""
    monkeypatch.chdir(tmp_path)

    inp = _base_input()
    inp["errors"] = ["e1", "e2", "e3", "e4"]
    mock_scout = AsyncMock(return_value=_FAKE_SCOUT_RAW)

    with (
        patch(_EXTRACT, new=AsyncMock(return_value=_FAKE_BRAND)),
        patch(_SCOUT, new=mock_scout),
        patch(_SCORE, new=AsyncMock(return_value=[])),
    ):
        result = await phase1_graph.ainvoke(inp)

    mock_scout.assert_not_called()
    assert result["report_url"] == ""


# ---------------------------------------------------------------------------
# 6. Analyst failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_results_on_analyst_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analyst failure → report still written with 0 scored stores; error recorded."""
    monkeypatch.chdir(tmp_path)

    candidates = [_scout_dict_to_candidate(r) for r in _FAKE_SCOUT_RAW]

    with (
        patch(_EXTRACT, new=AsyncMock(return_value=_FAKE_BRAND)),
        patch(_SCOUT, new=AsyncMock(return_value=_FAKE_SCOUT_RAW)),
        patch(_SCORE, new=AsyncMock(side_effect=RuntimeError("Groq down"))),
    ):
        result = await phase1_graph.ainvoke(_base_input())

    assert result["store_candidates"] == candidates
    assert result["scored_stores"] == []
    assert result["report_url"] != ""
    assert any("analyst" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 7–9. _scout_dict_to_candidate unit tests
# ---------------------------------------------------------------------------

def test_scout_dict_full_address() -> None:
    """Standard 3-segment address parses city and state correctly."""
    d = {
        "google_place_id": "ChIJ001",
        "name": "My Shop",
        "address": "123 Main St, Brooklyn, NY 11201",
        "instagram_handle": "@myshop",
    }
    c = _scout_dict_to_candidate(d)
    assert c.place_id == "ChIJ001"
    assert c.name == "My Shop"
    assert c.city == "Brooklyn"
    assert c.state == "NY"
    assert c.instagram_handle == "@myshop"
    assert c.is_chain is False


def test_scout_dict_missing_fields() -> None:
    """Empty dict defaults all fields without raising."""
    c = _scout_dict_to_candidate({})
    assert c.place_id == ""
    assert c.name == ""
    assert c.instagram_handle is None
    assert c.instagram_followers is None
    assert c.storefront_image_urls == []


def test_scout_dict_two_part_address() -> None:
    """2-part address 'City, ST' parses both segments."""
    c = _scout_dict_to_candidate({"address": "Brooklyn, NY"})
    assert c.city == "Brooklyn"
    assert c.state == "NY"
