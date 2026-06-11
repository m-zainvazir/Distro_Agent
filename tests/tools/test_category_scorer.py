"""Category scorer tests — all via curated-map fallback (no ML model required)."""

from app.models.brand_profile import BrandProfile
from app.models.store_candidate import StoreCandidate
from app.tools.category_scorer import _sim_to_score, score_category_alignment


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
        embedding_vector=[],
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


def test_cosmetics_store_scores_high_for_beauty_brand() -> None:
    result = score_category_alignment(_store(["cosmetics_store"]), _beauty_brand(), embedder=None)
    assert result.score >= 7.0, f"Expected >= 7.0, got {result.score}: {result.reasoning}"


def test_shoe_store_scores_low_for_beauty_brand() -> None:
    result = score_category_alignment(_store(["shoe_store"]), _beauty_brand(), embedder=None)
    assert result.score < 4.0, f"Expected < 4.0, got {result.score}: {result.reasoning}"


def test_embedding_failure_falls_back_to_curated_map() -> None:
    def _broken(text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")

    result = score_category_alignment(_store(["cosmetics_store"]), _beauty_brand(), embedder=_broken)
    assert result.score >= 7.0
    assert isinstance(result.score, float)


def test_unmapped_type_tokenises_gracefully() -> None:
    brand = BrandProfile(
        brand_name="X",
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
    result = score_category_alignment(_store(["rare_boutique_type"]), brand, embedder=None)
    assert result.score >= 4.0


def test_no_overlap_returns_minimum_score() -> None:
    result = score_category_alignment(_store(["hardware_store"]), _beauty_brand(), embedder=None)
    assert result.score <= 3.0


def test_sim_to_score_thresholds() -> None:
    assert _sim_to_score(0.60) >= 9.0
    assert 7.0 <= _sim_to_score(0.50) < 9.0
    assert 5.0 <= _sim_to_score(0.40) < 7.0
    assert 3.0 <= _sim_to_score(0.30) < 5.0
    assert 1.0 <= _sim_to_score(0.10) < 3.0


def test_precomputed_brand_vector_not_re_embedded() -> None:
    call_log: list[str] = []

    def _tracker(text: str) -> list[float]:
        call_log.append(text)
        return [1.0, 0.0, 0.0, 0.0]

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
        embedding_vector=[1.0, 0.0, 0.0, 0.0],
    )
    score_category_alignment(_store(["cosmetics_store"], "Botanica"), brand, embedder=_tracker)
    assert len(call_log) == 1, f"Expected 1 embedder call (store only), got {len(call_log)}"
