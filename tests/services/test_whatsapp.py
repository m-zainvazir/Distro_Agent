"""Tests for the WhatsApp service and webhook handler.

All external HTTP calls are mocked with respx.
Graph resume calls are mocked with unittest.mock.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.api.v1.webhooks import router as webhooks_router
from app.core.config import settings

# ---------------------------------------------------------------------------
# Test app — isolated FastAPI instance, no auth dependencies
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(webhooks_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PHONE = "15551234567"
_EMAIL_ID = "email-abc-123"
_STORE_NAME = "Brooklyn Indie Boutique"
_PREVIEW = "Hey, we think your store would love our skincare line..."

_WA_API_URL_PATTERN = "https://graph.facebook.com/v19.0"


def _make_signature(body: bytes, secret: str = "test-secret") -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _button_tap_payload(button_id: str) -> dict[str, Any]:
    """Build a minimal WhatsApp interactive button-reply webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": button_id,
                                            "title": "tapped",
                                        },
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


def _template_button_tap_payload(payload_id: str) -> dict[str, Any]:
    """Build a WhatsApp template quick-reply (type "button") webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "button",
                                    "button": {
                                        "payload": payload_id,
                                        "text": "tapped",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test 1 — send_approval_card posts the correct payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_send_approval_card_posts_correct_payload() -> None:
    """Approval card must POST an interactive message with two buttons."""
    from app.services.whatsapp_service import send_approval_card

    # Patch the phone number ID so the URL is predictable
    phone_number_id = "111222333"
    expected_url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"

    route = respx.post(expected_url).mock(return_value=Response(200, json={"messages": [{"id": "wamid.abc"}]}))

    with patch.object(settings, "whatsapp_phone_number_id", phone_number_id), \
         patch.object(settings, "whatsapp_access_token", "tok-test"):
        await send_approval_card(phone=_PHONE, email_preview=_PREVIEW, email_id=_EMAIL_ID)

    assert route.called, "WhatsApp messages endpoint was not called"

    sent_body: dict[str, Any] = json.loads(route.calls[0].request.content)

    # Structural assertions
    assert sent_body["type"] == "interactive"
    assert sent_body["to"] == _PHONE
    assert sent_body["messaging_product"] == "whatsapp"

    buttons: list[dict[str, Any]] = sent_body["interactive"]["action"]["buttons"]
    assert len(buttons) == 2, "Expected exactly 2 buttons"

    button_ids = {b["reply"]["id"] for b in buttons}
    assert f"approve:{_EMAIL_ID}" in button_ids, "Missing approve button"
    assert f"reject:{_EMAIL_ID}" in button_ids, "Missing reject button"


# ---------------------------------------------------------------------------
# Test 1b — send_approval_card posts a template payload when configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_send_approval_card_uses_template_when_configured() -> None:
    """When a template is configured, the card must POST a template message
    with the store/preview body params and per-button approve/reject payloads."""
    from app.services.whatsapp_service import send_approval_card

    phone_number_id = "111222333"
    expected_url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    route = respx.post(expected_url).mock(return_value=Response(200, json={"messages": [{"id": "wamid.t"}]}))

    # A preview with newlines/tabs must be flattened — templates reject them.
    messy_preview = "Line one\n\nLine two\twith tab"

    with patch.object(settings, "whatsapp_phone_number_id", phone_number_id), \
         patch.object(settings, "whatsapp_access_token", "tok-test"), \
         patch.object(settings, "whatsapp_approval_template", "outreach_approval_request"), \
         patch.object(settings, "whatsapp_approval_template_lang", "en_US"):
        await send_approval_card(
            phone=_PHONE, email_preview=messy_preview, email_id=_EMAIL_ID, store_name=_STORE_NAME
        )

    assert route.called
    sent_body: dict[str, Any] = json.loads(route.calls[0].request.content)

    assert sent_body["type"] == "template"
    template = sent_body["template"]
    assert template["name"] == "outreach_approval_request"
    assert template["language"]["code"] == "en_US"

    components = {c.get("sub_type", c["type"]): c for c in template["components"]}
    body_params = components["body"]["parameters"]
    assert body_params[0]["text"] == _STORE_NAME
    # Whitespace must be collapsed to a single line (no newlines/tabs).
    assert "\n" not in body_params[1]["text"] and "\t" not in body_params[1]["text"]
    assert body_params[1]["text"] == "Line one Line two with tab"

    # Quick-reply buttons carry the dynamic routing payloads at their indices.
    quick_replies = [c for c in template["components"] if c.get("sub_type") == "quick_reply"]
    by_index = {c["index"]: c["parameters"][0]["payload"] for c in quick_replies}
    assert by_index["0"] == f"approve:{_EMAIL_ID}"
    assert by_index["1"] == f"reject:{_EMAIL_ID}"


# ---------------------------------------------------------------------------
# Test 2 — GET verification challenge echoes hub.challenge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_verification_challenge() -> None:
    """GET with correct verify_token must return hub.challenge as plain text."""
    verify_token = "my-verify-token"
    challenge = "9876543210"

    with patch.object(settings, "whatsapp_verify_token", verify_token):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": verify_token,
                    "hub.challenge": challenge,
                },
            )

    assert resp.status_code == 200
    assert resp.text == challenge


# ---------------------------------------------------------------------------
# Test 3 — POST with invalid signature returns 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature() -> None:
    """POST with a bad X-Hub-Signature-256 header must return HTTP 403."""
    body = json.dumps({"object": "whatsapp_business_account"}).encode()
    bad_signature = "sha256=deadbeefdeadbeefdeadbeefdeadbeef"

    with patch.object(settings, "whatsapp_app_secret", "real-secret"):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": bad_signature,
                },
            )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 4 — approve tap calls resume_graph_for_email with approved=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_approve_tap_resumes_graph() -> None:
    """A valid approve:<id> button tap must call resume_graph_for_email(approved=True)."""
    secret = "test-app-secret"
    button_id = f"approve:{_EMAIL_ID}"
    payload = _button_tap_payload(button_id)
    body = json.dumps(payload).encode()
    signature = _make_signature(body, secret)

    mock_resume = AsyncMock()

    # whatsapp_service calls _resume_module.resume_graph_for_email where
    # _resume_module is the app.core.resume module object.  Patch the
    # attribute on that module so the call is intercepted.
    with patch.object(settings, "whatsapp_app_secret", secret), \
         patch("app.core.resume.resume_graph_for_email", mock_resume):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                },
            )

    assert resp.status_code == 200
    mock_resume.assert_awaited_once_with(email_id=_EMAIL_ID, approved=True)


# ---------------------------------------------------------------------------
# Test 5 — reject tap calls resume_graph_for_email with approved=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_reject_tap_resumes_graph() -> None:
    """A valid reject:<id> button tap must call resume_graph_for_email(approved=False)."""
    secret = "test-app-secret"
    button_id = f"reject:{_EMAIL_ID}"
    payload = _button_tap_payload(button_id)
    body = json.dumps(payload).encode()
    signature = _make_signature(body, secret)

    mock_resume = AsyncMock()

    # Same patch target as test 4 — the attribute on the imported resume module.
    with patch.object(settings, "whatsapp_app_secret", secret), \
         patch("app.core.resume.resume_graph_for_email", mock_resume):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                },
            )

    assert resp.status_code == 200
    mock_resume.assert_awaited_once_with(email_id=_EMAIL_ID, approved=False)


# ---------------------------------------------------------------------------
# Test 6 — template quick-reply tap (type "button") resumes the graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_template_button_tap_resumes_graph() -> None:
    """A template quick-reply tap (type "button", payload approve:<id>) must
    route to resume_graph_for_email(approved=True) just like an interactive tap."""
    secret = "test-app-secret"
    payload = _template_button_tap_payload(f"approve:{_EMAIL_ID}")
    body = json.dumps(payload).encode()
    signature = _make_signature(body, secret)

    mock_resume = AsyncMock()

    with patch.object(settings, "whatsapp_app_secret", secret), \
         patch("app.core.resume.resume_graph_for_email", mock_resume):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                },
            )

    assert resp.status_code == 200
    mock_resume.assert_awaited_once_with(email_id=_EMAIL_ID, approved=True)
