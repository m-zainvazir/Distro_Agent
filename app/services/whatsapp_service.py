"""WhatsApp Business API service.

Sends interactive approval cards and plain deal-alert notifications.
All HTTP calls use a shared async httpx client with retry/backoff for
transient 5xx errors and timeouts.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each attempt


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _messages_url() -> str:
    return f"{_GRAPH_API_BASE}/{settings.whatsapp_phone_number_id}/messages"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
) -> httpx.Response:
    """POST *payload* to *url*, retrying on 5xx or timeout up to _MAX_RETRIES."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.post(url, json=payload, headers=_auth_headers())
            if response.status_code < 500:
                return response
            # 5xx — log and retry
            logger.warning(
                "whatsapp_api_5xx",
                attempt=attempt,
                status_code=response.status_code,
                body=response.text[:200],
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "whatsapp_api_transport_error",
                attempt=attempt,
                error=str(exc),
            )

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

    if last_exc is not None:
        raise last_exc
    # If we exited the loop without a transport error, the last response was 5xx.
    return response  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def send_approval_card(
    phone: str,
    email_preview: str,
    email_id: str,
) -> None:
    """Send an interactive WhatsApp message with Approve / Reject buttons.

    The button reply payloads encode the email_id so the webhook handler can
    route the tap back to the correct paused graph:

        approve:<email_id>
        reject:<email_id>

    Args:
        phone: E.164 recipient phone number (e.g. "15551234567").
        email_preview: Short preview text shown in the message body.
        email_id: Unique identifier for the pending outreach email.
    """
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    f"Outreach email ready for review:\n\n{email_preview}\n\n"
                    "Tap a button to respond:"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"approve:{email_id}",
                            "title": "✅ Approve",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"reject:{email_id}",
                            "title": "✏️ Reject",
                        },
                    },
                ]
            },
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await _post_with_retry(client, _messages_url(), payload)
            if response.status_code not in (200, 201):
                logger.error(
                    "whatsapp_send_approval_card_failed",
                    phone=phone,
                    email_id=email_id,
                    status_code=response.status_code,
                    body=response.text[:200],
                )
            else:
                logger.info(
                    "whatsapp_send_approval_card_ok",
                    phone=phone,
                    email_id=email_id,
                )
        except Exception as exc:
            logger.error(
                "whatsapp_send_approval_card_exception",
                phone=phone,
                email_id=email_id,
                error=str(exc),
            )
            raise


async def send_deal_alert(
    phone: str,
    store_name: str,
    reply_summary: str,
) -> None:
    """Send a plain-text notification when a buyer replies positively.

    Args:
        phone: E.164 recipient phone number.
        store_name: Name of the store that replied.
        reply_summary: Short summary of the buyer's reply.
    """
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "body": (
                f"Deal alert! {store_name} replied positively.\n\n{reply_summary}"
            )
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await _post_with_retry(client, _messages_url(), payload)
            if response.status_code not in (200, 201):
                logger.error(
                    "whatsapp_send_deal_alert_failed",
                    phone=phone,
                    store_name=store_name,
                    status_code=response.status_code,
                    body=response.text[:200],
                )
            else:
                logger.info(
                    "whatsapp_send_deal_alert_ok",
                    phone=phone,
                    store_name=store_name,
                )
        except Exception as exc:
            logger.error(
                "whatsapp_send_deal_alert_exception",
                phone=phone,
                store_name=store_name,
                error=str(exc),
            )
            raise


async def process_incoming_message(payload: dict[str, Any]) -> None:
    """Parse an inbound WhatsApp webhook payload and route button taps.

    Handles interactive button replies whose IDs start with "approve:" or
    "reject:" and delegates to ``resume_graph_for_email``.

    Args:
        payload: The full webhook body sent by Meta.
    """
    # Import the module object (not just the function) so that
    # patch("app.core.resume.resume_graph_for_email", ...) intercepts the
    # attribute lookup at call time — keeping the function testable.
    import app.core.resume as resume_mod  # noqa: PLC0415

    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages: list[dict[str, Any]] = value.get("messages", [])

        for message in messages:
            msg_type: str = message.get("type", "")

            if msg_type != "interactive":
                logger.info(
                    "whatsapp_non_interactive_message_ignored",
                    msg_type=msg_type,
                )
                continue

            interactive: dict[str, Any] = message.get("interactive", {})
            button_reply: dict[str, Any] = interactive.get("button_reply", {})
            button_id: str = button_reply.get("id", "")

            if button_id.startswith("approve:"):
                email_id = button_id[len("approve:"):]
                logger.info(
                    "whatsapp_approve_tap",
                    email_id=email_id,
                )
                await resume_mod.resume_graph_for_email(email_id=email_id, approved=True)

            elif button_id.startswith("reject:"):
                email_id = button_id[len("reject:"):]
                logger.info(
                    "whatsapp_reject_tap",
                    email_id=email_id,
                )
                await resume_mod.resume_graph_for_email(email_id=email_id, approved=False)

            else:
                logger.info(
                    "whatsapp_unknown_button_id",
                    button_id=button_id,
                )

    except Exception as exc:
        logger.error(
            "whatsapp_process_incoming_message_failed",
            error=str(exc),
        )
        raise
