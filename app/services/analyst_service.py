from app.agents.analyst_agent import AnalystState, analyst_graph
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import ScoredStore, StoreCandidate


async def score_stores(
    brand_profile: BrandProfile,
    store_candidates: list[StoreCandidate],
    max_stores: int = 50,
) -> list[ScoredStore]:
    capped = store_candidates[:max_stores]

    initial_state: AnalystState = {
        "brand_profile": brand_profile,
        "store_candidates": capped,
        "current_index": 0,
        "scores_in_progress": [],
        "vision_calls_made": 0,
        "total_token_usage": {"input": 0, "output": 0},
        "total_cost_usd": 0.0,
        "scored_stores": [],
        "errors": [],
    }

    result = await analyst_graph.ainvoke(initial_state)

    errors: list[str] = result.get("errors", [])
    scored: list[ScoredStore] = result.get("scored_stores", [])
    vision_count: int = result.get("vision_calls_made", 0)
    total_cost: float = result.get("total_cost_usd", 0.0)

    logger.info(
        "analyst_service_complete",
        scored=len(scored),
        vision_ran_on=vision_count,
        total_cost_usd=total_cost,
    )

    if errors and not scored:
        raise ValueError(f"Analyst agent failed: {errors}")

    return scored
