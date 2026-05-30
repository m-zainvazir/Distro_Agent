from pydantic import BaseModel, ConfigDict


class StoreCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    place_id: str
    name: str
    address: str
    city: str
    state: str
    country: str = "US"
    google_categories: list[str]
    website_url: str | None
    instagram_handle: str | None
    instagram_followers: int | None
    instagram_posts_last_30_days: int | None
    storefront_image_urls: list[str]
    price_tier: str | None          # "$" | "$$" | "$$$" | "$$$$"
    review_snippets: list[str]
    is_chain: bool = False


class DimensionScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float                    # 0.0–10.0
    reasoning: str
    data_used: list[str]


class ScoredStore(BaseModel):
    model_config = ConfigDict(frozen=True)

    store: StoreCandidate

    visual_vibe_score: DimensionScore | None    # None if text_score < 8.0
    category_score: DimensionScore
    price_score: DimensionScore
    engagement_score: DimensionScore
    wholesale_score: DimensionScore

    text_score: float               # weighted avg of 4 text dimensions (0–10)
    final_score: float              # with or without vision (0–10)
    vision_was_run: bool

    match_summary: str
    why_matched: str
    outreach_priority: str          # "HIGH" | "MEDIUM" | "LOW"


# Priority thresholds
HIGH_THRESHOLD = 8.0
MEDIUM_THRESHOLD = 6.0


def compute_priority(final_score: float) -> str:
    if final_score >= HIGH_THRESHOLD:
        return "HIGH"
    if final_score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"
