"""Campaign endpoints — start outreach runs and handle HITL approve/reject."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.dependencies import get_current_tenant
from app.core.logging import logger
from app.models.campaign import Tenant

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class StartCampaignRequest(BaseModel):
    brand_profile_id: str
    store_ids: list[str]
    email_tone: str = "warm"


class ApprovalRequest(BaseModel):
    feedback: str = ""


class SimulateReplyRequest(BaseModel):
    reply_text: str
    sender_email: str = "buyer@store.com"
    email_id: str = "email-001"
    tenant_id: str = "tenant-test"


@router.post("/simulate-reply", status_code=status.HTTP_200_OK)
async def simulate_reply(
    body: SimulateReplyRequest,
    tenant: Tenant = Depends(get_current_tenant),
) -> dict:
    """Trigger the Reply Handler inside the server process for HITL testing.

    Returns the counter_id / proposal_id so the caller can immediately
    hit the approve/reject endpoint.
    """
    from app.agents.reply_handler_agent import build_reply_handler_graph
    from app.services.campaign_service import _pending_approvals

    graph = build_reply_handler_graph()
    result = await graph.ainvoke({
        "reply_text": body.reply_text,
        "sender_email": body.sender_email,
        "gmail_thread_id": f"thread-{body.email_id}",
        "email_id": body.email_id,
        "tenant_id": body.tenant_id,
        "intent": "",
        "routing_action": "",
        "notes": "",
    })

    pending_ids = list(_pending_approvals.keys())
    logger.info(
        "simulate_reply_complete",
        intent=result.get("intent"),
        routing_action=result.get("routing_action"),
        pending_ids=pending_ids,
    )
    return {
        "intent": result.get("intent"),
        "routing_action": result.get("routing_action"),
        "notes": result.get("notes"),
        "pending_approval_ids": pending_ids,
    }


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
async def start_campaign(
    body: StartCampaignRequest,
    tenant: Tenant = Depends(get_current_tenant),
) -> dict:
    logger.info(
        "campaign_start_requested",
        tenant_id=str(tenant.id),
        brand_profile_id=body.brand_profile_id,
        store_count=len(body.store_ids),
    )
    return {"status": "accepted", "message": "Campaign queued"}


@router.post("/{email_id}/approve", status_code=status.HTTP_200_OK)
async def approve_email(
    email_id: str,
    tenant: Tenant = Depends(get_current_tenant),
) -> dict:
    from app.services.campaign_service import get_pending_approval

    record = get_pending_approval(email_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

    if record.get("tenant_id", "") != str(tenant.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    try:
        from app.core.resume import resume_graph_for_email

        await resume_graph_for_email(email_id=email_id, approved=True)
    except Exception as exc:
        logger.error("campaign_approve_failed", email_id=email_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume graph",
        ) from exc

    return {"status": "approved"}


@router.post("/{email_id}/reject", status_code=status.HTTP_200_OK)
async def reject_email(
    email_id: str,
    body: ApprovalRequest,
    tenant: Tenant = Depends(get_current_tenant),
) -> dict:
    from app.services.campaign_service import get_pending_approval

    record = get_pending_approval(email_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

    if record.get("tenant_id", "") != str(tenant.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    try:
        from app.core.resume import resume_graph_for_email

        await resume_graph_for_email(email_id=email_id, approved=False)
    except Exception as exc:
        logger.error("campaign_reject_failed", email_id=email_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume graph",
        ) from exc

    return {"status": "rejected"}
