"""Governance gate — synchronous admin-approval checkpoint for high-stakes actions.

Intended call pattern (from Celery task at the synchronous level, BEFORE asyncio.run):

    from app.core.governance import require_admin_approval

    approved = require_admin_approval(
        action_type="update_scoring_weights",
        payload={"vertical": "footwear", "old": 0.35, "new": 0.40},
    )
    if not approved:
        return {"status": "skipped", "reason": "admin_rejected_or_timed_out"}

    result = asyncio.run(_async_work())

WARNING: require_admin_approval blocks the calling thread for up to timeout_seconds.
Only call from Celery task functions, never from within a running async event loop.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHANNEL_PREFIX = "governance:approval:"
_METADATA_PREFIX = "governance:token:"
_TOKEN_TTL = 7200       # Redis TTL for token metadata (2 hours)
_POLL_INTERVAL = 5.0    # seconds between pub/sub get_message polls
_SEP = ":"


# ---------------------------------------------------------------------------
# Token helpers (pure — no I/O)
# ---------------------------------------------------------------------------


def generate_approval_token(action_type: str, payload: dict[str, Any]) -> str:
    """Return ``{token_id}:{timestamp}:{hmac_hex}`` signed with SECRET_KEY.

    HMAC input: ``{action_type}:{token_id}:{timestamp}:{payload_json}``.
    Each call produces a unique token because token_id is a fresh UUID4.
    """
    token_id = uuid.uuid4().hex
    timestamp = str(int(time.time()))
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    message = _SEP.join([action_type, token_id, timestamp, payload_json])
    sig = hmac.new(
        settings.secret_key.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return _SEP.join([token_id, timestamp, sig])


def extract_token_id(token: str) -> str:
    """Return the token_id prefix from a full token string."""
    return token.split(_SEP, 1)[0]


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


def _redis_client() -> Any:
    import redis as _r  # local import — avoids loading redis at module import time

    return _r.from_url(settings.redis_url, decode_responses=True)


def store_token_metadata(
    token: str,
    action_type: str,
    payload: dict[str, Any],
) -> None:
    """Persist token → {action_type, payload} in Redis for HMAC re-verification."""
    r = _redis_client()
    try:
        r.set(
            f"{_METADATA_PREFIX}{extract_token_id(token)}",
            json.dumps(
                {"action_type": action_type, "payload": payload, "token": token},
                default=str,
            ),
            ex=_TOKEN_TTL,
        )
    finally:
        r.close()


def verify_token(token: str, action_type: str) -> bool:
    """Full HMAC verification using Redis-stored metadata.

    Returns False when the token is absent, expired, for a different action_type,
    or the HMAC doesn't match (tampered).
    """
    r = _redis_client()
    try:
        raw = r.get(f"{_METADATA_PREFIX}{extract_token_id(token)}")
    finally:
        r.close()

    if raw is None:
        return False

    try:
        meta: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return False

    if meta.get("action_type") != action_type:
        return False

    # Re-derive the HMAC from the stored token + payload and compare.
    stored_token: str = meta.get("token", "")
    parts = stored_token.split(_SEP, 2)
    if len(parts) != 3:
        return False

    tok_id, timestamp, received_sig = parts
    payload_json = json.dumps(meta.get("payload", {}), sort_keys=True, default=str)
    message = _SEP.join([action_type, tok_id, timestamp, payload_json])
    expected_sig = hmac.new(
        settings.secret_key.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_sig, received_sig)


def publish_approval_decision(token_id: str, *, approved: bool) -> None:
    """Publish 'approved' or 'rejected' to the Redis channel for this token."""
    r = _redis_client()
    try:
        r.publish(
            f"{_CHANNEL_PREFIX}{token_id}",
            "approved" if approved else "rejected",
        )
    finally:
        r.close()
    logger.info(
        "governance_decision_published",
        token_id=token_id,
        approved=approved,
    )


# ---------------------------------------------------------------------------
# Admin notification (synchronous httpx — safe from any call context)
# ---------------------------------------------------------------------------


def _admin_phone() -> str:
    """Return the admin phone: ADMIN_PHONE if set, else WHATSAPP_FOUNDER_PHONE."""
    return settings.admin_phone or settings.whatsapp_founder_phone


def send_approval_request(
    token: str,
    action_type: str,
    payload: dict[str, Any],
) -> None:
    """Send approve/reject links to admin via WhatsApp text message.

    Uses synchronous httpx.Client — no async event loop required.
    Logs a warning (doesn't raise) if WhatsApp is not configured.
    """

    phone = _admin_phone()
    if not phone:
        logger.warning(
            "governance_no_admin_phone",
            action_type=action_type,
            token_id=extract_token_id(token),
        )
        return

    base = settings.base_url.rstrip("/")
    approve_url = f"{base}/api/v1/governance/approve?token={token}&action={action_type}"
    reject_url = f"{base}/api/v1/governance/reject?token={token}&action={action_type}"
    payload_preview = json.dumps(payload, indent=2, default=str)[:300]

    body = (
        f"Admin approval required\n"
        f"Action: {action_type}\n\n"
        f"Details:\n{payload_preview}\n\n"
        f"Approve:\n{approve_url}\n\n"
        f"Reject:\n{reject_url}\n\n"
        f"This request expires in 1 hour."
    )

    wa_url = (
        f"https://graph.facebook.com/v19.0/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    wa_payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"body": body},
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(wa_url, json=wa_payload, headers=headers)
        if resp.status_code not in (200, 201):
            logger.error(
                "governance_notify_send_failed",
                status_code=resp.status_code,
                action_type=action_type,
            )
        else:
            logger.info(
                "governance_notify_sent",
                action_type=action_type,
                token_id=extract_token_id(token),
            )
    except Exception as exc:
        logger.error(
            "governance_notify_exception",
            action_type=action_type,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Blocking wait (Redis pub/sub)
# ---------------------------------------------------------------------------


def wait_for_approval(token: str, timeout_seconds: int = 3600) -> bool:
    """Block this thread until admin approves/rejects or timeout expires.

    Polls Redis pub/sub in _POLL_INTERVAL-second chunks.

    Returns:
        True  — admin clicked Approve
        False — admin clicked Reject, or timeout expired without a decision
    """
    token_id = extract_token_id(token)
    channel = f"{_CHANNEL_PREFIX}{token_id}"

    r = _redis_client()
    pubsub = r.pubsub(ignore_subscribe_messages=True)

    try:
        pubsub.subscribe(channel)
        logger.info(
            "governance_waiting",
            token_id=token_id,
            timeout_seconds=timeout_seconds,
        )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            msg = pubsub.get_message(timeout=min(remaining, _POLL_INTERVAL))
            if msg is not None and msg["type"] == "message":
                approved = msg["data"] == "approved"
                logger.info(
                    "governance_decision_received",
                    token_id=token_id,
                    approved=approved,
                )
                return approved

        logger.warning(
            "governance_timed_out",
            token_id=token_id,
            timeout_seconds=timeout_seconds,
        )
        return False

    finally:
        try:
            pubsub.unsubscribe(channel)
            pubsub.close()
        finally:
            r.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def require_admin_approval(
    action_type: str,
    payload: dict[str, Any],
    timeout_seconds: int = 3600,
) -> bool:
    """Gate a high-stakes action behind admin approval via WhatsApp link.

    Steps:
      1. Generate HMAC-signed token (unique per call)
      2. Store token metadata in Redis (enables HMAC re-verification at click time)
      3. Send approve/reject URL to admin via WhatsApp
      4. Block this thread until admin clicks or timeout_seconds elapses

    Returns True only on explicit approval. Returns False on rejection or timeout.
    """
    token = generate_approval_token(action_type, payload)
    token_id = extract_token_id(token)

    logger.info(
        "governance_approval_requested",
        action_type=action_type,
        token_id=token_id,
    )

    store_token_metadata(token, action_type, payload)
    send_approval_request(token, action_type, payload)
    return wait_for_approval(token, timeout_seconds=timeout_seconds)
