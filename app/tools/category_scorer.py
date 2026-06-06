import math
from collections.abc import Callable

from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, StoreCandidate

# Generic Google place types that carry no aesthetic signal — dropped before matching.
_GENERIC_GOOGLE_TYPES: set[str] = {
    "point", "interest", "establishment", "store", "premise", "food",
    "general", "contractor", "point_of_interest",
}

# Calibration for bge-small cosine similarity → 0–10 score. Related retail text
# typically lands ~0.55–0.80; unrelated ~0.30–0.45.
_SIM_FLOOR = 0.30
_SIM_CEIL = 0.78


def _clean_store_text(store: StoreCandidate) -> str:
    """Build a readable category string from Google's compound types + reviews.

    e.g. ["cosmetics_store", "point_of_interest"] -> "cosmetics" (noise dropped),
    so a "cosmetics_store" can match a brand whose products are makeup/lip care.
    """
    terms: list[str] = []
    for cat in store.google_categories:
        for tok in cat.replace("_", " ").split():
            if tok.lower() not in _GENERIC_GOOGLE_TYPES:
                terms.append(tok)
    parts = [store.name, *terms, *store.review_snippets[:3]]
    return " ".join(p for p in parts if p)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _keyword_score(store: StoreCandidate, brand: BrandProfile) -> DimensionScore:
    """Original exact-token overlap scorer — used as a fallback when no embedder
    is supplied (keeps unit tests fast and deterministic)."""
    brand_keywords: set[str] = {
        kw.lower() for kw in brand.product_categories + brand.aesthetic_keywords
    }

    store_text = (
        " ".join(store.google_categories) + " " + " ".join(store.review_snippets)
    ).lower()
    store_keywords: set[str] = {word for word in store_text.split() if len(word) > 3}

    matched = brand_keywords & store_keywords
    overlap = len(matched)

    if overlap >= 5:
        score = 9.0 + min((overlap - 5) * 0.2, 1.0)
    elif overlap >= 3:
        score = 7.0 + (overlap - 3) * 0.95
    elif overlap >= 1:
        score = 4.0 + (overlap - 1) * 1.45
    else:
        score = 1.5

    score = round(min(score, 10.0), 2)

    if matched:
        reasoning = f"Matched {overlap} keyword(s): {', '.join(sorted(matched)[:5])}."
    else:
        reasoning = "No keyword overlap between brand categories and store profile."

    return DimensionScore(score=score, reasoning=reasoning, data_used=list(matched)[:10])


def score_category_alignment(
    store: StoreCandidate,
    brand: BrandProfile,
    embedder: Callable[[str], list[float]] | None = None,
) -> DimensionScore:
    """Score how well a store's categories fit the brand.

    When an ``embedder`` is provided, uses semantic cosine similarity between the
    brand's category/aesthetic profile and the store's (cleaned) categories — this
    bridges vocabulary gaps like Google's "cosmetics_store" vs a brand's "makeup".
    Falls back to exact-keyword overlap when no embedder is given or embedding fails.
    """
    if embedder is None:
        return _keyword_score(store, brand)

    try:
        brand_text = (
            f"{brand.brand_name}. "
            f"{', '.join(brand.product_categories)}. "
            f"{', '.join(brand.aesthetic_keywords)}"
        )
        store_text = _clean_store_text(store)
        sim = _cosine(embedder(brand_text), embedder(store_text))
        scaled = (sim - _SIM_FLOOR) / (_SIM_CEIL - _SIM_FLOOR) * 10.0
        score = round(max(0.0, min(scaled, 10.0)), 2)
        return DimensionScore(
            score=score,
            reasoning=(
                f"Semantic similarity {sim:.2f} between brand categories "
                f"({', '.join(brand.product_categories[:3])}) and store profile "
                f"({store_text[:60]})."
            ),
            data_used=store.google_categories[:10],
        )
    except Exception:
        # Any embedding failure → degrade gracefully to keyword matching.
        return _keyword_score(store, brand)
