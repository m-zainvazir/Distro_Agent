import math
from collections.abc import Callable

from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, StoreCandidate
from app.tools.category_map import GOOGLE_TYPE_TO_CONSUMER_TERMS

_NOISE: set[str] = {
    "point", "interest", "establishment", "store", "premise", "food",
    "general", "contractor", "point_of_interest",
}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _sim_to_score(sim: float) -> float:
    """Map cosine similarity to 0-10 using spec threshold buckets."""
    if sim > 0.55:
        return round(min(9.0 + (sim - 0.55) / 0.25, 10.0), 2)
    if sim >= 0.45:
        return round(7.0 + (sim - 0.45) / 0.10 * 1.9, 2)
    if sim >= 0.35:
        return round(5.0 + (sim - 0.35) / 0.10 * 1.9, 2)
    if sim >= 0.25:
        return round(3.0 + (sim - 0.25) / 0.10 * 1.9, 2)
    return round(max(1.0, 1.0 + sim / 0.25 * 1.9), 2)


def _expand_categories(categories: list[str]) -> list[str]:
    """Expand Google place types via curated map; unmapped types fall back to tokenisation."""
    terms: list[str] = []
    for cat in categories:
        mapped = GOOGLE_TYPE_TO_CONSUMER_TERMS.get(cat)
        if mapped:
            terms.extend(mapped)
        else:
            for tok in cat.replace("_", " ").split():
                if tok.lower() not in _NOISE:
                    terms.append(tok)
    return terms


def _clean_store_text(store: StoreCandidate) -> str:
    """Build embedding-ready text from store metadata using map-expanded categories."""
    parts = [store.name, *_expand_categories(store.google_categories), *store.review_snippets[:3]]
    return " ".join(p for p in parts if p)


def _curated_map_score(store: StoreCandidate, brand: BrandProfile) -> DimensionScore:
    """Keyword overlap after curated map expansion — fallback when no embedder."""
    brand_terms: set[str] = set()
    for kw in brand.product_categories + brand.aesthetic_keywords:
        for word in kw.lower().split():
            if len(word) > 3:
                brand_terms.add(word)

    store_terms: set[str] = set()
    for term in _expand_categories(store.google_categories):
        for word in term.lower().split():
            if len(word) > 3:
                store_terms.add(word)
    for snippet in store.review_snippets[:3]:
        for word in snippet.lower().split():
            if len(word) > 3:
                store_terms.add(word)

    matched = brand_terms & store_terms
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
    reasoning = (
        f"Matched {overlap} term(s) via curated map: {', '.join(sorted(matched)[:5])}."
        if matched
        else "No term overlap between brand categories and store profile."
    )
    return DimensionScore(score=score, reasoning=reasoning, data_used=list(matched)[:10])


# ---------------------------------------------------------------------------
# Primary: embedding-based cosine similarity
# ---------------------------------------------------------------------------

def score_category_alignment(
    store: StoreCandidate,
    brand: BrandProfile,
    embedder: Callable[[str], list[float]] | None = None,
) -> DimensionScore:
    """Score category alignment.

    Primary (embedder provided): uses brand.embedding_vector directly, embeds store
    text, maps cosine similarity through spec threshold buckets.
    Fallback (no embedder or exception): curated-map keyword overlap.
    """
    if embedder is None:
        return _curated_map_score(store, brand)

    try:
        brand_vec = brand.embedding_vector if brand.embedding_vector else embedder(
            f"{brand.brand_name}. "
            f"{', '.join(brand.product_categories)}. "
            f"{', '.join(brand.aesthetic_keywords)}"
        )
        store_text = _clean_store_text(store)
        store_vec = embedder(store_text)
        sim = _cosine(brand_vec, store_vec)
        return DimensionScore(
            score=_sim_to_score(sim),
            reasoning=f"Semantic similarity {sim:.2f} (brand vs store: {store_text[:60]}).",
            data_used=store.google_categories[:10],
        )
    except Exception:
        return _curated_map_score(store, brand)
