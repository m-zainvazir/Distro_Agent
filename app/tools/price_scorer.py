from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, StoreCandidate

_TIER_RANGES: dict[str, tuple[float, float]] = {
    "$": (5.0, 30.0),
    "$$": (25.0, 80.0),
    "$$$": (70.0, 200.0),
    "$$$$": (180.0, 600.0),
}
_DEFAULT_RANGE = (25.0, 80.0)


def _overlap_fraction(a: tuple[float, float], b: tuple[float, float]) -> float:
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    if hi <= lo:
        return 0.0
    overlap = hi - lo
    shorter_span = min(a[1] - a[0], b[1] - b[0])
    return overlap / shorter_span if shorter_span > 0 else 0.0


def score_price_alignment(store: StoreCandidate, brand: BrandProfile) -> DimensionScore:
    low_confidence = store.price_tier is None
    store_range = _TIER_RANGES.get(store.price_tier or "", _DEFAULT_RANGE)
    brand_range = brand.price_range

    frac = _overlap_fraction(store_range, brand_range)

    if frac >= 1.0:
        score = 9.5
    elif frac >= 0.5:
        score = round(7.0 + (frac - 0.5) * 3.0, 2)
    elif frac > 0.0:
        score = round(5.0 + frac * 4.0, 2)
    else:
        # Check adjacency
        gap = max(store_range[0] - brand_range[1], brand_range[0] - store_range[1])
        score = round(max(2.0, 6.5 - gap / 50.0), 2)

    score = min(score, 10.0)

    tier_label = store.price_tier or "unknown"
    confidence_note = " (low confidence — no price tier data)" if low_confidence else ""
    reasoning = (
        f"Brand sells ${brand_range[0]:.0f}–${brand_range[1]:.0f}; "
        f"store carries {tier_label} products (${store_range[0]:.0f}–${store_range[1]:.0f}){confidence_note}."
    )

    return DimensionScore(
        score=score,
        reasoning=reasoning,
        data_used=["price_tier"] if not low_confidence else [],
    )
