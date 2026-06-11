from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_tenant
from app.models.brand_profile import BrandProfile
from app.models.campaign import Tenant
from app.models.store_candidate import ScoredStore, StoreCandidate
from app.services.analyst_service import score_stores

router = APIRouter(prefix="/scoring", tags=["scoring"])


class ScoreBatchRequest(BaseModel):
    brand_profile: BrandProfile
    store_candidates: list[StoreCandidate]
    max_stores: int = Field(default=50, ge=1, le=100)


class ScoreBatchResponse(BaseModel):
    scored_stores: list[ScoredStore]
    vision_ran_on: int
    total_cost_usd: float
    high_priority_count: int
    medium_priority_count: int


@router.post("/score-batch", response_model=ScoreBatchResponse)
async def score_batch(
    request: ScoreBatchRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> ScoreBatchResponse:
    try:
        scored = await score_stores(
            brand_profile=request.brand_profile,
            store_candidates=request.store_candidates,
            max_stores=request.max_stores,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    vision_ran_on = sum(1 for s in scored if s.vision_was_run)
    total_cost = sum(0.0 for _ in scored)

    return ScoreBatchResponse(
        scored_stores=scored,
        vision_ran_on=vision_ran_on,
        total_cost_usd=total_cost,
        high_priority_count=sum(1 for s in scored if s.outreach_priority == "HIGH"),
        medium_priority_count=sum(1 for s in scored if s.outreach_priority == "MEDIUM"),
    )
