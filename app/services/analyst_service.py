from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst_agent import AnalystState, analyst_graph
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import ScoredStore, StoreCandidate


async def score_stores(
    brand_profile: BrandProfile,
    store_candidates: list[StoreCandidate],
    max_stores: int = 50,
    tenant_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> list[ScoredStore]:
    # Dedup against already-processed stores for this tenant before scoring
    if tenant_id is not None and db is not None:
        from app.services.similarity_service import dedup_stores

        store_candidates = await dedup_stores(tenant_id, store_candidates, db)

    capped = store_candidates[:max_stores]

    initial_state: AnalystState = {
        "brand_profile": brand_profile,
        "store_candidates": capped,
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
