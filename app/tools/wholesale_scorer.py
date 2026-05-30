import httpx

from app.core.logging import logger
from app.models.store_candidate import DimensionScore, StoreCandidate

STRONG_SIGNALS = [
    "wholesale", "wholesale inquiry", "carry our brand", "stockist",
    "buy wholesale", "minimum order", "trade account",
]
MEDIUM_SIGNALS = [
    "curated", "independent brands", "small batch", "locally sourced",
    "handmade", "artisan", "boutique brands",
]
WEAK_SIGNALS = ["new arrivals", "exclusive", "limited edition"]


def _scan_text(text: str) -> tuple[float, list[str]]:
    text_lower = text.lower()
    hits: list[str] = []
    total = 0.0

    for sig in STRONG_SIGNALS:
        if sig in text_lower:
            total += 2.5
            hits.append(sig)

    for sig in MEDIUM_SIGNALS:
        if sig in text_lower:
            total += 1.5
            hits.append(sig)

    for sig in WEAK_SIGNALS:
        if sig in text_lower:
            total += 0.5
            hits.append(sig)

    return min(total, 10.0), hits


async def score_wholesale_signals(store: StoreCandidate) -> DimensionScore:
    review_text = " ".join(store.review_snippets)
    score, hits = _scan_text(review_text)
    sources = ["review_snippets"]

    if store.website_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(store.website_url)
                web_text = response.text[:10_000]
            web_score, web_hits = _scan_text(web_text)
            score = min(score + web_score, 10.0)
            hits.extend(web_hits)
            sources.append("website")
        except Exception as exc:
            logger.warning(
                "wholesale_website_fetch_failed",
                store=store.name,
                url=store.website_url,
                error=str(exc),
            )

    score = round(score, 2)

    if hits:
        reasoning = f"Found wholesale signals: {', '.join(dict.fromkeys(hits))[:120]}."
    else:
        reasoning = "No wholesale signals detected in reviews or website."

    return DimensionScore(
        score=score,
        reasoning=reasoning,
        data_used=sources,
    )
