"""Governance approval endpoints.

Admin clicks approve/reject links that were sent via WhatsApp.
Security: HMAC token in the URL — no JWT required.
The HMAC is re-verified against Redis-stored metadata before publishing any decision.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.core.governance import extract_token_id, publish_approval_decision, verify_token
from app.core.logging import logger

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/approve", status_code=status.HTTP_200_OK)
async def approve_action(
    token: str = Query(..., description="HMAC-signed token from the approval request"),
    action: str = Query(..., description="Action type being approved"),
) -> dict[str, str]:
    """Admin taps this link to approve a pending governance action.

    Verifies the HMAC token, then publishes 'approved' to the Redis channel
    that require_admin_approval() is blocking on.
    """
    if not verify_token(token, action):
        logger.warning("governance_approve_invalid_token", action=action)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "INVALID_TOKEN", "message": "Token is invalid or expired"},
        )

    token_id = extract_token_id(token)
    publish_approval_decision(token_id, approved=True)
    logger.info("governance_approved_via_link", action=action, token_id=token_id)
    return {"status": "approved", "action": action}


@router.get("/reject", status_code=status.HTTP_200_OK)
async def reject_action(
    token: str = Query(..., description="HMAC-signed token from the approval request"),
    action: str = Query(..., description="Action type being rejected"),
) -> dict[str, str]:
    """Admin taps this link to reject a pending governance action.

    Verifies the HMAC token, then publishes 'rejected' to the Redis channel
    that require_admin_approval() is blocking on.
    """
    if not verify_token(token, action):
        logger.warning("governance_reject_invalid_token", action=action)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "INVALID_TOKEN", "message": "Token is invalid or expired"},
        )

    token_id = extract_token_id(token)
    publish_approval_decision(token_id, approved=False)
    logger.info("governance_rejected_via_link", action=action, token_id=token_id)
    return {"status": "rejected", "action": action}
