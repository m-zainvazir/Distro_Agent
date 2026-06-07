"""Category scorer tests — all run via the curated-map fallback (no ML model needed)."""

from app.models.brand_profile import BrandProfile
from app.models.store_candidate import StoreCandidate
from app.tools.category_scorer import _sim_to_score, score_category_alignment

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _beauty_brand() -> BrandProfile:
    return BrandProfile(
        brand_name="Glow Lab",
        tagline="Clean beauty essentials",
        primary_colors=["#FDE8D8"],
        aesthetic_keywords=["clean beauty", "botanical", "skincare", "fragrance"],
        product_categories=["skincare", "makeup", "lip care"],
        price_range=(18.0, 85.0),
        brand_voice_description="Warm and minimal.",
        wholesale_readiness_score=7.0,
        raw_product_images=[],
        embedding_vector=[],  # empty → curated-map fallback used
    )


def _store(google_categories: list[str], name: str = "Test Store") -> StoreCandidate:
    return StoreCandidate(
        place_id=f"place_{name}",
        name=name,
        address="123 Main St",
        city="New York",
        state="NY",
        google_categories=google_categories,
        website_url=None,
        instagram_handle=None,
        instagram_followers=None,
        instagram_posts_last_30_days=None,
        price_tier=None,
        review_snippets=[],
        storefront_image_urls=[],
    )


# ---------------------------------------------------------------------------
# Acceptance criteria tests (spec §Acceptance Criteria)
# ---------------------------------------------------------------------------


def test_cosmetics_store_scores_high_for_beauty_brand() -> None:
    """AC1: cosmetics_store >= 7.0 for a beauty brand."""
    store = _store(["cosmetics_store"])
    brand = _beauty_brand()
    result = score_category_alignment(store, brand, embedder=None)
    assert result.score >= 7.0, (
        f"Expected >= 7.0 for cosmetics_store vs beauty brand, got {result.score}. "
        f"Reasoning: {result.reasoning}"
    )


def test_shoe_store_scores_low_for_beauty_brand() -> None:
    """AC2: shoe_store < 4.0 for a beauty brand (no term overlap)."""
    store = _store(["shoe_store"])
    brand = _beauty_brand()
    result = score_category_alignment(store, brand, embedder=None)
    assert result.score < 4.0, (
        f"Expected < 4.0 for shoe_store vs beauty brand, got {result.score}. "
        f"Reasoning: {result.reasoning}"
    )


def test_embedding_failure_falls_back_to_curated_map() -> None:
    """AC3: embedding failure falls back to curated map without crashing."""
    def _broken_embedder(text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")

    store = _store(["cosmetics_store"])
    brand = _beauty_brand()
    # Should not raise — must return a DimensionScore via fallback
    result = score_category_alignment(store, brand, embedder=_broken_embedder)
    assert result.score >= 7.0  # curated map still works
    assert isinstance(result.score, float)


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_unmapped_type_falls_back_to_tokenisation() -> None:
    """A Google type not in the curated map is split on '_' with noise stripped."""
    store = _store(["rare_boutique_type"])
    brand = BrandProfile(
        brand_name="Brand",
        tagline="",
        primary_colors=[],
        aesthetic_keywords=["boutique", "rare"],
        product_categories=["lifestyle"],
        price_range=(10.0, 50.0),
        brand_voice_description="",
        wholesale_readiness_score=5.0,
        raw_product_images=[],
        embedding_vector=[],
    )
    result = score_category_alignment(store, brand, embedder=None)
    # "boutique" and "rare" should match the tokenised type
    assert result.score >= 4.0


def test_no_overlap_returns_minimum_score() -> None:
    """A hardware store should score the minimum against a beauty brand."""
    store = _store(["hardware_store"])
    brand = _beauty_brand()
    result = score_category_alignment(store, brand, embedder=None)
    assert result.score <= 3.0


def test_sim_to_score_thresholds() -> None:
    """Similarity thresholds map to the correct score buckets."""
    assert _sim_to_score(0.60) >= 9.0   # > 0.55 → 9-10
    assert _sim_to_score(0.50) >= 7.0   # 0.45-0.55 → 7-8.9
    assert _sim_to_score(0.50) < 9.0
    assert _sim_to_score(0.40) >= 5.0   # 0.35-0.45 → 5-6.9
    assert _sim_to_score(0.40) < 7.0
    assert _sim_to_score(0.30) >= 3.0   # 0.25-0.35 → 3-4.9
    assert _sim_to_score(0.30) < 5.0
    assert _sim_to_score(0.10) >= 1.0   # < 0.25 → 1-2.9
    assert _sim_to_score(0.10) < 3.0


def test_embedding_path_uses_precomputed_brand_vector() -> None:
    """When brand.embedding_vector is set, the embedder is only called once (for the store)."""
    call_log: list[str] = []

    def _tracking_embedder(text: str) -> list[float]:
        call_log.append(text)
        # Return a fixed 4-dim vector; brand and store will be identical → sim=1.0
        return [1.0, 0.0, 0.0, 0.0]

    store = _store(["cosmetics_store"], name="Botanica")
    brand = BrandProfile(
        brand_name="Glow",
        tagline="",
        primary_colors=[],
        aesthetic_keywords=["beauty"],
        product_categories=["skincare"],
        price_range=(20.0, 60.0),
        brand_voice_description="",
        wholesale_readiness_score=6.0,
        raw_product_images=[],
        embedding_vector=[1.0, 0.0, 0.0, 0.0],  # pre-computed — must NOT trigger a second embed call
    )
    result = score_category_alignment(store, brand, embedder=_tracking_embedder)
    # Embedder should only be called for the store text, not the brand
    assert len(call_log) == 1, f"Expected 1 embedder call (store only), got {len(call_log)}: {call_log}"
    assert result.score >= 9.0  # cosine sim of identical vectors = 1.0 → score 10
