import json
from collections.abc import Callable
from typing import Literal

from groq import AsyncGroq
from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.core.llm import groq_chat
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import (
    DimensionScore,
    ScoredStore,
    StoreCandidate,
    compute_priority,
)
from app.tools.category_scorer import score_category_alignment
from app.tools.embedding_generator import embed_text
from app.tools.engagement_scorer import score_engagement
from app.tools.price_scorer import score_price_alignment
from app.tools.vision_scorer import score_visual_vibe
from app.tools.wholesale_scorer import score_wholesale_signals

# Embedder used for semantic category scoring. Module-level so tests can patch it
# to None (falling back to fast, deterministic keyword matching).
_CATEGORY_EMBEDDER: Callable[[str], list[float]] | None = embed_text


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AnalystState(TypedDict):
    brand_profile: BrandProfile
    store_candidates: list[StoreCandidate]

    scores_in_progress: list[ScoredStore]

    vision_calls_made: int
    total_token_usage: dict[str, int]
    total_cost_usd: float

    scored_stores: list[ScoredStore]
    errors: list[str]


# ---------------------------------------------------------------------------
# Text dimension weights (the 4 non-vision dimensions, normalised to 1.0)
# ---------------------------------------------------------------------------

# Base weights for the 4 text dimensions (25/20/10/10 of the overall 65% text share).
_BASE_WEIGHTS = {
    "category": 0.25,
    "price": 0.20,
    "engagement": 0.10,
    "wholesale": 0.10,
}

# Groq llama-3.3-70b pricing: $0.59 / $0.79 per 1M tokens
_COST_PER_1K_INPUT = 0.00059
_COST_PER_1K_OUTPUT = 0.00079


def _compute_text_score(
    cat: DimensionScore,
    price: DimensionScore,
    eng: DimensionScore,
    wholesale: DimensionScore,
    available: dict[str, bool],
) -> float:
    """Weighted average over the dimensions we actually have data for.

    Price, engagement, and wholesale signals are often unavailable for stores
    discovered purely via Google Places (no price tier, Instagram, or reviews).
    Scoring those as ~0 unfairly drags down a strong category match, so we
    re-normalise the weights over only the dimensions with real input data.
    When all four are present this is identical to the original fixed weighting.
    """
    scores = {
        "category": cat.score,
        "price": price.score,
        "engagement": eng.score,
        "wholesale": wholesale.score,
    }
    active = {k: w for k, w in _BASE_WEIGHTS.items() if available.get(k, True)}
    total = sum(active.values())
    if total == 0:
        return round(cat.score, 3)
    return round(sum(scores[k] * (active[k] / total) for k in active), 3)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def validate_inputs_node(state: AnalystState) -> dict:
    errors: list[str] = list(state.get("errors", []))

    if state.get("brand_profile") is None:
        errors.append("brand_profile is required")
    if not state.get("store_candidates"):
        errors.append("store_candidates must be a non-empty list")

    if errors:
        logger.warning("analyst_validation_failed", errors=errors)

    return {"errors": errors}


async def score_text_dimensions_node(state: AnalystState) -> dict:
    brand: BrandProfile = state["brand_profile"]
    candidates: list[StoreCandidate] = state["store_candidates"]
    scores_in_progress: list[ScoredStore] = []
    errors: list[str] = list(state.get("errors", []))

    for store in candidates:
        try:
            cat_score = score_category_alignment(store, brand, embedder=_CATEGORY_EMBEDDER)
            price_score = score_price_alignment(store, brand)
            eng_score = score_engagement(store)
            wholesale_score = await score_wholesale_signals(store)

            available = {
                "category": bool(store.google_categories),
                "price": store.price_tier is not None,
                "engagement": (
                    store.instagram_followers is not None
                    or store.instagram_posts_last_30_days is not None
                ),
                "wholesale": bool(store.review_snippets),
            }
            text_score = _compute_text_score(
                cat_score, price_score, eng_score, wholesale_score, available
            )

            partial = ScoredStore(
                store=store,
                visual_vibe_score=None,
                category_score=cat_score,
                price_score=price_score,
                engagement_score=eng_score,
                wholesale_score=wholesale_score,
                text_score=text_score,
                final_score=text_score,        # will be updated after vision
                vision_was_run=False,
                match_summary="",
                why_matched="",
                outreach_priority=compute_priority(text_score),
            )
            scores_in_progress.append(partial)
        except Exception as exc:
            logger.warning("text_scoring_failed", store=store.name, error=str(exc))
            errors.append(f"text_scoring:{store.name}: {exc}")

    logger.info("analyst_text_scoring_complete", count=len(scores_in_progress))
    return {"scores_in_progress": scores_in_progress, "errors": errors}


async def score_vision_node(state: AnalystState) -> dict:
    brand: BrandProfile = state["brand_profile"]
    threshold: float = settings.vision_score_threshold
    vision_calls = int(state.get("vision_calls_made", 0))
    token_usage: dict[str, int] = dict(state.get("total_token_usage", {"input": 0, "output": 0}))
    cost = float(state.get("total_cost_usd", 0.0))

    updated: list[ScoredStore] = []

    for scored in state["scores_in_progress"]:
        # Tier gate: score must exceed VISION_MIN_SCORE (settings.vision_score_threshold)
        if scored.text_score < threshold:
            updated.append(scored)
            continue

        # Per-lead budget gate (Layers 14 & 16)
        from app.core.budget import LeadBudget  # noqa: PLC0415

        lead_id = str(scored.store.place_id or scored.store.name)
        _vision_est = (300 / 1000) * _COST_PER_1K_INPUT + (100 / 1000) * _COST_PER_1K_OUTPUT
        lead_budget = LeadBudget(
            lead_id=lead_id,
            max_tokens=settings.max_tokens_per_lead,
            max_cost_usd=settings.max_cost_per_lead_usd,
        )
        if not lead_budget.check_and_reserve(_vision_est, estimated_tokens=400):
            updated.append(scored)
            continue

        try:
            vibe = await score_visual_vibe(scored.store, brand)
        except Exception as exc:
            logger.warning("vision_score_failed", store=scored.store.name, error=str(exc))
            updated.append(scored)
            continue
        vision_calls += 1

        final_score = round(
            (vibe.score * 0.35) + (scored.text_score * 0.65), 3
        )

        # Track batch-level totals for state reporting
        token_usage["input"] = token_usage.get("input", 0) + 300
        token_usage["output"] = token_usage.get("output", 0) + 100
        cost += _vision_est

        updated.append(
            ScoredStore(
                store=scored.store,
                visual_vibe_score=vibe,
                category_score=scored.category_score,
                price_score=scored.price_score,
                engagement_score=scored.engagement_score,
                wholesale_score=scored.wholesale_score,
                text_score=scored.text_score,
                final_score=final_score,
                vision_was_run=True,
                match_summary="",
                why_matched="",
                outreach_priority=compute_priority(final_score),
            )
        )

    logger.info("analyst_vision_scoring_complete", vision_calls=vision_calls)
    return {
        "scores_in_progress": updated,
        "vision_calls_made": vision_calls,
        "total_token_usage": token_usage,
        "total_cost_usd": round(cost, 6),
    }


_SUMMARY_SYSTEM = """\
You are a wholesale distribution analyst. Given scoring data for a retail store, write:
- match_summary: 2-sentence summary of why this store is or isn't a match
- why_matched: 1 specific sentence citing the strongest alignment signal

Respond with ONLY valid JSON: {"match_summary": "...", "why_matched": "..."}
"""


async def compute_final_scores_node(state: AnalystState) -> dict:
    brand: BrandProfile = state["brand_profile"]
    finalized: list[ScoredStore] = []
    token_usage: dict[str, int] = dict(state.get("total_token_usage", {"input": 0, "output": 0}))
    cost = float(state.get("total_cost_usd", 0.0))

    from app.core.budget import LeadBudget  # noqa: PLC0415

    _summary_est = (300 / 1000) * _COST_PER_1K_INPUT + (200 / 1000) * _COST_PER_1K_OUTPUT

    for scored in state["scores_in_progress"]:
        vision_line = ""
        if scored.visual_vibe_score:
            vision_line = f"Visual vibe score: {scored.visual_vibe_score.score}/10\n"

        prompt = (
            f"Brand: {brand.brand_name}\n"
            f"Store: {scored.store.name}, {scored.store.city}\n"
            f"Category score: {scored.category_score.score}/10 — {scored.category_score.reasoning}\n"
            f"Price score: {scored.price_score.score}/10 — {scored.price_score.reasoning}\n"
            f"Engagement score: {scored.engagement_score.score}/10\n"
            f"Wholesale score: {scored.wholesale_score.score}/10\n"
            f"{vision_line}"
            f"Final score: {scored.final_score}/10\n"
        )

        # Per-lead budget gate before summary LLM call
        lead_id = str(scored.store.place_id or scored.store.name)
        lead_budget = LeadBudget(
            lead_id=lead_id,
            max_tokens=settings.max_tokens_per_lead,
            max_cost_usd=settings.max_cost_per_lead_usd,
        )
        if not lead_budget.check_and_reserve(_summary_est, estimated_tokens=500):
            match_summary = f"{scored.store.name} scored {scored.final_score:.1f}/10 overall."
            why_matched = scored.category_score.reasoning
            finalized.append(
                ScoredStore(
                    store=scored.store,
                    visual_vibe_score=scored.visual_vibe_score,
                    category_score=scored.category_score,
                    price_score=scored.price_score,
                    engagement_score=scored.engagement_score,
                    wholesale_score=scored.wholesale_score,
                    text_score=scored.text_score,
                    final_score=scored.final_score,
                    vision_was_run=scored.vision_was_run,
                    match_summary=match_summary,
                    why_matched=why_matched,
                    outreach_priority=scored.outreach_priority,
                )
            )
            continue

        try:
            response = await groq_chat(
                AsyncGroq,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=settings.groq_model,
                response_format={"type": "json_object"},
                temperature=0.4,
                max_tokens=200,
            )
            parsed = json.loads(response.choices[0].message.content or "")
            match_summary = parsed.get("match_summary", "")
            why_matched = parsed.get("why_matched", "")

            assert response.usage is not None
            token_usage["input"] = token_usage.get("input", 0) + response.usage.prompt_tokens
            token_usage["output"] = token_usage.get("output", 0) + response.usage.completion_tokens
            cost += (
                (response.usage.prompt_tokens / 1000) * _COST_PER_1K_INPUT
                + (response.usage.completion_tokens / 1000) * _COST_PER_1K_OUTPUT
            )
        except Exception as exc:
            logger.warning("analyst_summary_failed", store=scored.store.name, error=str(exc))
            match_summary = f"{scored.store.name} scored {scored.final_score:.1f}/10 overall."
            why_matched = scored.category_score.reasoning

        finalized.append(
            ScoredStore(
                store=scored.store,
                visual_vibe_score=scored.visual_vibe_score,
                category_score=scored.category_score,
                price_score=scored.price_score,
                engagement_score=scored.engagement_score,
                wholesale_score=scored.wholesale_score,
                text_score=scored.text_score,
                final_score=scored.final_score,
                vision_was_run=scored.vision_was_run,
                match_summary=match_summary,
                why_matched=why_matched,
                outreach_priority=scored.outreach_priority,
            )
        )

    logger.info(
        "groq_token_usage",
        node="compute_final_scores",
        model=settings.groq_model,
        input_tokens=token_usage.get("input", 0),
        output_tokens=token_usage.get("output", 0),
    )

    return {
        "scores_in_progress": finalized,
        "total_token_usage": token_usage,
        "total_cost_usd": round(cost, 6),
    }


async def sort_and_package_node(state: AnalystState) -> dict:
    scored = sorted(
        state["scores_in_progress"],
        key=lambda s: s.final_score,
        reverse=True,
    )
    logger.info(
        "analyst_complete",
        total=len(scored),
        vision_calls=state.get("vision_calls_made", 0),
        total_cost_usd=state.get("total_cost_usd", 0.0),
    )
    return {"scored_stores": scored}


async def error_node(state: AnalystState) -> dict:
    logger.error("analyst_error_node", errors=state.get("errors"))
    partial = state.get("scores_in_progress", [])
    return {"scored_stores": sorted(partial, key=lambda s: s.final_score, reverse=True)}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_validate(state: AnalystState) -> Literal["score_text_dimensions", "error"]:
    if state.get("errors"):
        return "error"
    return "score_text_dimensions"


def route_after_text_scoring(state: AnalystState) -> Literal["score_vision", "compute_final_scores"]:
    vision_candidates = [
        s for s in state.get("scores_in_progress", [])
        if s.text_score >= settings.vision_score_threshold
    ]
    return "score_vision" if vision_candidates else "compute_final_scores"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(AnalystState)

    graph.add_node("validate_inputs", validate_inputs_node)
    graph.add_node("score_text_dimensions", score_text_dimensions_node)
    graph.add_node("score_vision", score_vision_node)
    graph.add_node("compute_final_scores", compute_final_scores_node)
    graph.add_node("sort_and_package", sort_and_package_node)
    graph.add_node("error", error_node)

    graph.set_entry_point("validate_inputs")
    graph.add_conditional_edges("validate_inputs", route_after_validate)
    graph.add_conditional_edges("score_text_dimensions", route_after_text_scoring)
    graph.add_edge("score_vision", "compute_final_scores")
    graph.add_edge("compute_final_scores", "sort_and_package")
    graph.add_edge("sort_and_package", END)
    graph.add_edge("error", END)

    return graph


analyst_graph = _build_graph().compile()
