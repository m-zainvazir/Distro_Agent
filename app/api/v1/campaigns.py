"""Campaign API — start outreach campaigns and handle HITL approve/reject."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.copywriter_agent import build_copywriter_graph
from app.core.checkpointer import get_checkpointer
from app.core.dependencies import get_current_tenant
from app.core.logging import logger
from app.models.campaign import Tenant
from app.services.campaign_service import start_email_campaign

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

# AsyncPostgresSaver in production; MemorySaver fallback when libpq unavailable.
_checkpointer = get_checkpointer()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CampaignStartRequest(BaseModel):
    scored_stores: list[dict]  # ScoredStore dicts from /discovery/{id}/report
    brand_profile: dict  # BrandProfile dict
    founder_name: str
    email_tone: str = "warm"  # "warm" | "professional" | "casual"


class CampaignStartResponse(BaseModel):
    thread_ids: list[str]
    stores_queued: int


class ApprovalRequest(BaseModel):
    feedback: str = ""


class ApprovalResponse(BaseModel):
    status: str
    thread_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start", response_model=CampaignStartResponse, status_code=202)
async def start_campaign(
    body: CampaignStartRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> CampaignStartResponse:
    """Kick off the CopywriterAgent for each HIGH/MEDIUM priority store.

    The agent drafts, self-critiques, and pauses at HITL — nothing sends.
    """
    from app.models.brand_profile import BrandProfile
    from app.models.store_candidate import ScoredStore

    stores = [ScoredStore(**s) for s in body.scored_stores]
    brand = BrandProfile(**body.brand_profile)

    thread_ids = await start_email_campaign(
        stores=stores,
        brand_profile=brand,
        founder_name=body.founder_name,
        email_tone=body.email_tone,
        tenant_id=str(tenant.id),
        checkpointer=_checkpointer,
    )

    return CampaignStartResponse(thread_ids=thread_ids, stores_queued=len(thread_ids))


@router.post("/{thread_id}/approve", response_model=ApprovalResponse)
async def approve_email(
    thread_id: str,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> ApprovalResponse:
    """Resume the paused graph with approval=True."""
    graph = build_copywriter_graph(checkpointer=_checkpointer)
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    try:
        await graph.ainvoke(Command(resume=True), config=config)
        logger.info("email_approved_via_api", thread_id=thread_id)
    except Exception as exc:
        logger.error("approve_failed", thread_id=thread_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Resume failed: {exc}") from exc

    return ApprovalResponse(status="approved", thread_id=thread_id)


@router.post("/{thread_id}/reject", response_model=ApprovalResponse)
async def reject_email(
    thread_id: str,
    body: ApprovalRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> ApprovalResponse:
    """Resume the paused graph with approval=False. The agent will re-draft."""
    graph = build_copywriter_graph(checkpointer=_checkpointer)
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    try:
        await graph.ainvoke(Command(resume=False), config=config)
        logger.info("email_rejected_via_api", thread_id=thread_id, feedback=body.feedback[:80])
    except Exception as exc:
        logger.error("reject_failed", thread_id=thread_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Resume failed: {exc}") from exc

    return ApprovalResponse(status="rejected_redrafting", thread_id=thread_id)
