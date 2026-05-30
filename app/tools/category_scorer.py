from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, StoreCandidate


def score_category_alignment(store: StoreCandidate, brand: BrandProfile) -> DimensionScore:
    brand_keywords: set[str] = {
        kw.lower() for kw in brand.product_categories + brand.aesthetic_keywords
    }

    store_text = (
        " ".join(store.google_categories)
        + " "
        + " ".join(store.review_snippets)
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

    return DimensionScore(
        score=score,
        reasoning=reasoning,
        data_used=list(matched)[:10],
    )
