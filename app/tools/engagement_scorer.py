from app.models.store_candidate import DimensionScore, StoreCandidate


def _follower_score(followers: int) -> float:
    if followers >= 10_000:
        return 10.0
    if followers >= 5_000:
        return 8.0
    if followers >= 1_000:
        return 6.0
    if followers >= 500:
        return 4.0
    return 2.0


def _activity_score(posts: int | None) -> float:
    if posts is None or posts == 0:
        return 1.0
    if posts >= 12:
        return 10.0
    if posts >= 8:
        return 7.5
    if posts >= 4:
        return 5.0
    return 3.0


def score_engagement(store: StoreCandidate) -> DimensionScore:
    if store.instagram_followers is None:
        return DimensionScore(
            score=4.0,
            reasoning="No Instagram data available.",
            data_used=[],
        )

    f_score = _follower_score(store.instagram_followers)
    a_score = _activity_score(store.instagram_posts_last_30_days)
    score = round((f_score * 0.6) + (a_score * 0.4), 2)

    reasoning = (
        f"{store.instagram_followers:,} followers (score {f_score}/10); "
        f"{store.instagram_posts_last_30_days or 0} posts/30 days (score {a_score}/10)."
    )

    return DimensionScore(
        score=score,
        reasoning=reasoning,
        data_used=["instagram_followers", "instagram_posts_last_30_days"],
    )
