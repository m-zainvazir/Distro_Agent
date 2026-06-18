"""Per-lead token/cost budget endpoints (Spec 303 — Blueprint Layers 14 & 16)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.budget import LeadBudget
from app.core.config import settings
from app.core.dependencies import get_current_tenant
from app.models.campaign import Tenant

router = APIRouter(prefix="/budget", tags=["budget"])


class BudgetConfigResponse(BaseModel):
    max_tokens_per_lead: int
    max_cost_per_lead_usd: float


class BudgetCheckRequest(BaseModel):
    lead_id: str
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0


class BudgetCheckResponse(BaseModel):
    lead_id: str
    allowed: bool
    remaining_tokens: int
    remaining_cost_usd: float
    max_tokens: int
    max_cost_usd: float


@router.get("/config", response_model=BudgetConfigResponse)
async def get_budget_config(
    _tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> BudgetConfigResponse:
    """Return the configured per-lead token and cost limits."""
    return BudgetConfigResponse(
        max_tokens_per_lead=settings.max_tokens_per_lead,
        max_cost_per_lead_usd=settings.max_cost_per_lead_usd,
    )


@router.post("/check", response_model=BudgetCheckResponse)
async def check_lead_budget(
    body: BudgetCheckRequest,
    _tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> BudgetCheckResponse:
    """Simulate a budget gate for a lead without committing spend.

    Returns whether the estimated call would be allowed under current limits,
    and how much budget would remain if it were approved.
    """
    budget = LeadBudget(
        lead_id=body.lead_id,
        max_tokens=settings.max_tokens_per_lead,
        max_cost_usd=settings.max_cost_per_lead_usd,
    )
    allowed = budget.check_and_reserve(
        estimated_cost=body.estimated_cost_usd,
        estimated_tokens=body.estimated_tokens,
    )
    return BudgetCheckResponse(
        lead_id=body.lead_id,
        allowed=allowed,
        remaining_tokens=budget.remaining_tokens,
        remaining_cost_usd=budget.remaining_cost_usd,
        max_tokens=settings.max_tokens_per_lead,
        max_cost_usd=settings.max_cost_per_lead_usd,
    )
