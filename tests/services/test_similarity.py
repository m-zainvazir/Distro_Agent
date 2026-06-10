"""Tests for similarity_service — cosine search, store dedup, privacy guarantees."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.store_candidate import StoreCandidate
from app.services.similarity_service import SimilarBrand, dedup_stores, find_similar_brands

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.uuid4()
_BRAND_ID = uuid.uuid4()
_OTHER_BRAND_ID = uuid.uuid4()


def _make_store(place_id: str) -> StoreCandidate:
    return StoreCandidate(
        place_id=place_id,
        name=f"Store {place_id}",
        address="123 Main St",
        city="Brooklyn",
        state="NY",
        google_categories=["gift_shop"],
        website_url=None,
        instagram_handle=None,
        instagram_followers=None,
        instagram_posts_last_30_days=None,
        storefront_image_urls=[],
        price_tier="$$",
        review_snippets=[],
    )


def _make_qdrant_hit(brand_id: str, score: float, keywords: list[str]) -> MagicMock:
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "brand_id": brand_id,
        "aesthetic_keywords": keywords,
        "price_range_min": 20.0,
        "price_range_max": 100.0,
        "product_categories": ["skincare", "wellness"],
    }
    return hit


def _make_db_record(brand_id: uuid.UUID, keywords: list[str]) -> MagicMock:
    record = MagicMock()
    record.id = brand_id
    record.embedding_vector = [0.1] * 10
    record.aesthetic_keywords = keywords
    return record


def _make_mock_db(record: MagicMock | None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# find_similar_brands — returns k results, excludes self
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_similar_brands_returns_k_results() -> None:
    record = _make_db_record(_BRAND_ID, ["minimal", "clean", "natural"])
    hits = [
        _make_qdrant_hit(str(uuid.uuid4()), 0.95, ["minimal", "organic"]),
        _make_qdrant_hit(str(uuid.uuid4()), 0.88, ["clean", "natural"]),
        _make_qdrant_hit(str(uuid.uuid4()), 0.81, ["artisan"]),
    ]

    mock_response = MagicMock()
    mock_response.points = hits
    mock_client = MagicMock()
    mock_client.query_points = AsyncMock(return_value=mock_response)

    with (
        patch("app.services.similarity_service.get_qdrant_client", return_value=mock_client),
        patch("app.services.similarity_service.AsyncSessionLocal") as mock_session,
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=_make_mock_db(record))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_ctx

        results = await find_similar_brands(_TENANT_ID, _BRAND_ID, k=3)

    assert len(results) == 3
    assert all(isinstance(r, SimilarBrand) for r in results)
    assert results[0].similarity_score == 0.95


@pytest.mark.asyncio
async def test_find_similar_brands_excludes_self() -> None:
    record = _make_db_record(_BRAND_ID, ["minimal", "clean"])
    # First hit is self, second is another brand
    hits = [
        _make_qdrant_hit(str(_BRAND_ID), 1.0, ["minimal", "clean"]),   # self
        _make_qdrant_hit(str(uuid.uuid4()), 0.91, ["minimal", "organic"]),
    ]

    mock_response = MagicMock()
    mock_response.points = hits
    mock_client = MagicMock()
    mock_client.query_points = AsyncMock(return_value=mock_response)

    with (
        patch("app.services.similarity_service.get_qdrant_client", return_value=mock_client),
        patch("app.services.similarity_service.AsyncSessionLocal") as mock_session,
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=_make_mock_db(record))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_ctx

        results = await find_similar_brands(_TENANT_ID, _BRAND_ID, k=5)

    assert len(results) == 1
    # Self (score 1.0) must not appear
    assert results[0].similarity_score == 0.91


@pytest.mark.asyncio
async def test_find_similar_brands_returns_empty_when_brand_not_found() -> None:
    with (
        patch("app.services.similarity_service.AsyncSessionLocal") as mock_session,
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=_make_mock_db(None))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_ctx

        results = await find_similar_brands(_TENANT_ID, _BRAND_ID, k=5)

    assert results == []


# ---------------------------------------------------------------------------
# Privacy — SimilarBrand has no PII fields
# ---------------------------------------------------------------------------


def test_similar_brand_model_has_no_pii_fields() -> None:
    """SimilarBrand must not expose any field that could identify a competitor."""
    pii_field_names = {
        "brand_name", "tenant_id", "email", "phone",
        "store_list", "contact", "address", "brand_url",
    }
    model_fields = set(SimilarBrand.model_fields.keys())
    leaked = pii_field_names & model_fields
    assert not leaked, f"PII fields exposed in SimilarBrand: {leaked}"


def test_cross_tenant_data_is_anonymized() -> None:
    """SimilarBrand values carry no cross-tenant identifying information."""
    brand = SimilarBrand(
        similarity_score=0.92,
        shared_aesthetic_keywords=["minimal", "clean"],
        price_range=(25.0, 150.0),
        shared_product_categories=["skincare"],
    )
    serialised = brand.model_dump()

    forbidden_keys = {"brand_name", "tenant_id", "email", "phone", "store_list"}
    assert not (forbidden_keys & set(serialised.keys()))


# ---------------------------------------------------------------------------
# dedup_stores
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_stores_removes_existing_place_ids() -> None:
    candidates = [
        _make_store("place_new"),
        _make_store("place_existing_1"),
        _make_store("place_existing_2"),
    ]

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("place_existing_1",), ("place_existing_2",)]
    db.execute = AsyncMock(return_value=mock_result)

    result = await dedup_stores(tenant_id=_TENANT_ID, candidates=candidates, db=db)

    assert len(result) == 1
    assert result[0].place_id == "place_new"


@pytest.mark.asyncio
async def test_dedup_stores_keeps_all_new_stores() -> None:
    candidates = [_make_store("place_a"), _make_store("place_b")]

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []   # nothing already in DB
    db.execute = AsyncMock(return_value=mock_result)

    result = await dedup_stores(tenant_id=_TENANT_ID, candidates=candidates, db=db)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_dedup_stores_empty_candidates_returns_empty() -> None:
    db = AsyncMock()
    result = await dedup_stores(tenant_id=_TENANT_ID, candidates=[], db=db)
    assert result == []
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Analyst pipeline integration — dedup called before scoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_stores_calls_dedup_when_tenant_provided() -> None:
    from app.models.brand_profile import BrandProfile
    from app.services.analyst_service import score_stores

    brand = BrandProfile(
        brand_name="TestBrand",
        tagline="test",
        primary_colors=[],
        aesthetic_keywords=["minimal"],
        product_categories=["skincare"],
        price_range=(10.0, 100.0),
        brand_voice_description="warm",
        wholesale_readiness_score=8.0,
        raw_product_images=[],
        embedding_vector=[0.1] * 10,
    )
    candidates = [_make_store("place_x"), _make_store("place_y")]
    scored_result: list[Any] = []

    mock_db = AsyncMock()
    mock_dedup = AsyncMock(return_value=candidates)  # pass-through

    with (
        patch("app.services.similarity_service.dedup_stores", mock_dedup),
        patch("app.services.analyst_service.analyst_graph") as mock_graph,
    ):
        mock_graph.ainvoke = AsyncMock(
            return_value={"scored_stores": [], "errors": [], "vision_calls_made": 0, "total_cost_usd": 0.0}
        )
        await score_stores(
            brand_profile=brand,
            store_candidates=candidates,
            tenant_id=_TENANT_ID,
            db=mock_db,
        )

    mock_dedup.assert_awaited_once_with(_TENANT_ID, candidates, mock_db)
