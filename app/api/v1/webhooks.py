"""WhatsApp Business API webhook handler.

GET  /api/v1/webhooks/whatsapp  — Meta verification challenge
POST /api/v1/webhooks/whatsapp  — Inbound message handler (signature-verified)

Security model
--------------
The POST handler MUST verify the X-Hub-Signature-256 header before executing
any business logic.  Invalid or missing signatures are rejected with HTTP 403.
No JWT authentication is applied — Meta sends unauthenticated GET challenges
during webhook setup, and POST requests are protected purely by signature.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.logging import logger
from app.services.whatsapp_service import process_incoming_message

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Verification challenge (Meta webhook setup)
# ---------------------------------------------------------------------------


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> Any:
    """Respond to Meta's one-time verification challenge.

    Meta sends a GET with hub.mode=subscribe and the token we configured in
    the developer console.  We echo hub.challenge if the token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("whatsapp_webhook_verified")
        # Return the challenge as plain text so Meta recognises the handshake.
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(content=hub_challenge)

    logger.warning(
        "whatsapp_webhook_verify_failed",
        hub_mode=hub_mode,
        token_match=(hub_verify_token == settings.whatsapp_verify_token),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": "WEBHOOK_VERIFY_FAILED", "message": "Token mismatch"},
    )


# ---------------------------------------------------------------------------
# Inbound message handler
# ---------------------------------------------------------------------------


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Return True iff the X-Hub-Signature-256 header matches the computed HMAC.

    Args:
        body: Raw request body bytes.
        signature_header: Value of the X-Hub-Signature-256 header, or None.

    Returns:
        True when the signature is present and valid, False otherwise.
    """
    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    received_digest = signature_header[len("sha256="):]
    secret = settings.whatsapp_app_secret.encode("utf-8")
    expected_digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_digest, received_digest)


@router.post("/whatsapp", status_code=status.HTTP_200_OK)
async def receive_webhook(request: Request) -> dict[str, str]:
    """Handle inbound messages from the WhatsApp Business API.

    The signature is verified before any payload parsing occurs.
    Returns HTTP 200 on success so Meta does not retry the delivery.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not _verify_signature(body, signature):
        logger.warning(
            "whatsapp_webhook_invalid_signature",
            signature=signature,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "INVALID_SIGNATURE",
                "message": "Webhook signature verification failed",
            },
        )

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        logger.error("whatsapp_webhook_json_parse_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_JSON", "message": "Request body is not valid JSON"},
        ) from exc

    logger.info("whatsapp_webhook_received", object_type=payload.get("object"))

    try:
        await process_incoming_message(payload)
    except Exception as exc:
        logger.error("whatsapp_webhook_processing_failed", error=str(exc))
        # Return 200 anyway — Meta will retry on non-2xx, causing duplicate processing.
        return {"status": "error", "detail": str(exc)}

    return {"status": "ok"}
