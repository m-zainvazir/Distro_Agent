"""Calibration service: correlate vibe_score with outcomes and nudge ScoringWeights.

Algorithm
---------
1. Pull all OutreachEmails sent in the last N days that have a decided outcome
   (converted, ignored, or a replied email with a clear intent).
2. Join to StoreCandidate to get the vibe_score that was predicted at send time.
3. Compute Pearson r between vibe_score and a binary win flag.
4. If |sample| >= MIN_SAMPLE:
   - r > 0.30  → visual_weight += NUDGE  (capped at VISUAL_MAX)
   - r < 0.05  → visual_weight -= NUDGE  (floored at VISUAL_MIN)
   - Renormalize the four non-visual weights proportionally so sum stays 1.0.
5. Persist updated row; return a report dict for the Celery task to forward.

Only vibe_score is available per-store today.  Category/price/engagement/wholesale
dimension scores are not persisted, so those weights can only be adjusted manually
or via future instrumentation.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.logging import logger
from app.models.campaign import OutreachCampaign, OutreachEmail, StoreCandidate
from app.models.scoring_weights import ScoringWeights

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_SAMPLE: int = 10        # minimum decided outcomes before touching weights
_LOOKBACK_DAYS: int = 30
_WEIGHT_NUDGE: float = 0.05
_VISUAL_MIN: float = 0.20
_VISUAL_MAX: float = 0.50

_BUCKETS: list[tuple[float, float]] = [
    (0.0, 2.0),
    (2.0, 4.0),
    (4.0, 6.0),
    (6.0, 8.0),
    (8.0, 10.01),
]
_BUCKET_LABELS: list[str] = ["0-2", "2-4", "4-6", "6-8", "8-10"]

# Outcome values that count as a WIN
_WIN_OUTCOMES: frozenset[str] = frozenset({"converted"})
_WIN_INTENTS: frozenset[str] = frozenset({"INTERESTED", "MEETING_REQUEST"})
# Outcome values that count as a LOSS
_LOSS_OUTCOMES: frozenset[str] = frozenset({"ignored"})
_LOSS_INTENTS: frozenset[str] = frozenset({"NOT_INTERESTED"})


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — easy to unit-test)
# ---------------------------------------------------------------------------


def classify_outcome(email: Any) -> str:
    """Return 'win', 'loss', or 'neutral' for a single OutreachEmail row."""
    outcome: str = getattr(email, "outcome", "") or ""
    intent: str = getattr(email, "reply_intent", "") or ""

    if outcome in _WIN_OUTCOMES:
        return "win"
    if intent in _WIN_INTENTS and outcome == "replied":
        return "win"
    if outcome in _LOSS_OUTCOMES:
        return "loss"
    if intent in _LOSS_INTENTS and outcome == "replied":
        return "loss"
    return "neutral"


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson r between two equal-length lists. Returns 0.0 for degenerate input."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return 0.0
    return num / (den_x * den_y)


def _nudge_and_renormalize(
    row: ScoringWeights,
    correlation: float,
) -> bool:
    """Apply weight nudge in-place. Returns True if any weight changed."""
    old_visual = row.visual_weight
    new_visual = old_visual

    if correlation > 0.30:
        new_visual = min(old_visual + _WEIGHT_NUDGE, _VISUAL_MAX)
    elif correlation < 0.05:
        new_visual = max(old_visual - _WEIGHT_NUDGE, _VISUAL_MIN)

    if new_visual == old_visual:
        return False

    non_visual_total = (
        row.category_weight
        + row.price_weight
        + row.engagement_weight
        + row.wholesale_weight
    )
    remaining = 1.0 - new_visual
    scale = remaining / non_visual_total if non_visual_total > 0 else 1.0

    row.visual_weight = round(new_visual, 4)
    row.category_weight = round(row.category_weight * scale, 4)
    row.price_weight = round(row.price_weight * scale, 4)
    row.engagement_weight = round(row.engagement_weight * scale, 4)
    row.wholesale_weight = round(row.wholesale_weight * scale, 4)
    return True


# ---------------------------------------------------------------------------
# DB-backed functions
# ---------------------------------------------------------------------------


async def get_weights(vertical_tag: str, db: AsyncSession) -> ScoringWeights:
    """Return the ScoringWeights row for *vertical_tag*, or an unsaved default if absent."""
    result = await db.execute(
        select(ScoringWeights).where(ScoringWeights.vertical_tag == vertical_tag)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ScoringWeights(vertical_tag=vertical_tag)
    return row


async def calibrate_weights(
    vertical_tag: str,
    db: AsyncSession,
    lookback_days: int = _LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Analyse recent outcomes, update weights for *vertical_tag*, return report dict.

    The DB row is only updated when ``sample_size >= _MIN_SAMPLE`` to avoid
    thrashing weights on too little data.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    # ── 1. Fetch emails in window joined to their store ──────────────────────
    if vertical_tag == "all":
        # Global calibration — all campaigns
        email_q = await db.execute(
            select(OutreachEmail, StoreCandidate)
            .join(StoreCandidate, OutreachEmail.store_id == StoreCandidate.id)
            .where(
                OutreachEmail.sent_at >= cutoff,
                OutreachEmail.outcome.in_(
                    ["converted", "ignored", "replied", "sent"]
                ),
            )
        )
    else:
        # Per-vertical: filter through campaign's vertical_tag
        email_q = await db.execute(
            select(OutreachEmail, StoreCandidate)
            .join(StoreCandidate, OutreachEmail.store_id == StoreCandidate.id)
            .join(OutreachCampaign, OutreachEmail.campaign_id == OutreachCampaign.id)
            .where(
                OutreachEmail.sent_at >= cutoff,
                OutreachEmail.outcome.in_(
                    ["converted", "ignored", "replied", "sent"]
                ),
                OutreachCampaign.vertical_tag == vertical_tag,
            )
        )

    rows = email_q.all()

    # ── 2. Classify and build correlation lists ──────────────────────────────
    vibe_scores: list[float] = []
    win_flags: list[float] = []
    bucket_counts: list[int] = [0] * len(_BUCKETS)
    bucket_wins: list[int] = [0] * len(_BUCKETS)
    wins = losses = 0

    for email, store in rows:
        classification = classify_outcome(email)
        vibe = float(store.vibe_score or 0.0)

        if classification == "win":
            vibe_scores.append(vibe)
            win_flags.append(1.0)
            wins += 1
        elif classification == "loss":
            vibe_scores.append(vibe)
            win_flags.append(0.0)
            losses += 1
        else:
            continue  # neutral emails don't inform the correlation

        for i, (lo, hi) in enumerate(_BUCKETS):
            if lo <= vibe < hi:
                bucket_counts[i] += 1
                if classification == "win":
                    bucket_wins[i] += 1
                break

    neutral = len(rows) - wins - losses
    total = len(rows)
    sample_size = wins + losses
    conversion_rate = round(wins / max(total, 1) * 100, 1)

    bucket_win_rates: dict[str, str] = {
        label: (
            f"{round(bucket_wins[i] / bucket_counts[i] * 100, 1)}% ({bucket_counts[i]} emails)"
            if bucket_counts[i]
            else "0% (0 emails)"
        )
        for i, label in enumerate(_BUCKET_LABELS)
    }

    # ── 3. Compute correlation and maybe update weights ──────────────────────
    correlation = pearson_correlation(vibe_scores, win_flags)

    result = await db.execute(
        select(ScoringWeights).where(ScoringWeights.vertical_tag == vertical_tag)
    )
    weights_row = result.scalar_one_or_none()
    if weights_row is None:
        # Column(default=...) is DB-side only; set Python-level defaults explicitly.
        weights_row = ScoringWeights(
            vertical_tag=vertical_tag,
            visual_weight=0.35,
            category_weight=0.25,
            price_weight=0.20,
            engagement_weight=0.10,
            wholesale_weight=0.10,
            sample_size=0,
        )
        db.add(weights_row)

    old_visual = weights_row.visual_weight
    weights_updated = False

    if sample_size >= _MIN_SAMPLE:
        weights_updated = _nudge_and_renormalize(weights_row, correlation)
        weights_row.calibrated_at = datetime.now(timezone.utc)
        weights_row.sample_size = sample_size
        await db.commit()
    else:
        logger.info(
            "calibration_skipped_low_sample",
            vertical=vertical_tag,
            sample_size=sample_size,
            min_required=_MIN_SAMPLE,
        )

    logger.info(
        "calibration_complete",
        vertical=vertical_tag,
        total=total,
        wins=wins,
        losses=losses,
        sample_size=sample_size,
        correlation=round(correlation, 3),
        weights_updated=weights_updated,
        new_visual_weight=weights_row.visual_weight,
    )

    return {
        "vertical_tag": vertical_tag,
        "lookback_days": lookback_days,
        "total_emails": total,
        "wins": wins,
        "losses": losses,
        "neutral": neutral,
        "conversion_rate_pct": conversion_rate,
        "sample_size": sample_size,
        "visual_correlation": round(correlation, 3),
        "bucket_win_rates": bucket_win_rates,
        "weights_updated": weights_updated,
        "old_visual_weight": old_visual,
        "new_visual_weight": weights_row.visual_weight,
        "current_weights": {
            "visual": weights_row.visual_weight,
            "category": weights_row.category_weight,
            "price": weights_row.price_weight,
            "engagement": weights_row.engagement_weight,
            "wholesale": weights_row.wholesale_weight,
        },
    }
