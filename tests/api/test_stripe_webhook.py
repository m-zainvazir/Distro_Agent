"""Tests for the Stripe webhook handler — all Stripe SDK and DB calls mocked."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import stripe
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.stripe_webhook import router as stripe_webhook_router

# ---------------------------------------------------------------------------
# Isolated test app
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(stripe_webhook_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_invoice_event(
    event_type: str,
    invoice_id: str = "in_test",
    email_id: str = "550e8400-e29b-41d4-a716-446655440000",
    customer_email: str = "buyer@store.com",
    amount_paid: int = 100000,
) -> dict[str, Any]:
    return {
        "id": "evt_test",
        "type": event_type,
        "data": {
            "object": {
                "id": invoice_id,
                "customer_email": customer_email,
                "amount_paid": amount_paid,
                "metadata": {"email_id": email_id, "tenant_id": "tenant-abc"},
            }
        },
    }


def _valid_sig_patch() -> Any:
    """Patch construct_webhook_event to return a controllable event dict."""
    return patch("app.api.v1.stripe_webhook.construct_webhook_event")


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_signature_returns_400() -> None:
    with patch(
        "app.api.v1.stripe_webhook.construct_webhook_event",
        side_effect=stripe.error.SignatureVerificationError("bad", sig_header="x"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/stripe",
                content=b"bad-payload",
                headers={"Stripe-Signature": "t=1,v1=bad"},
            )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_SIGNATURE"


# ---------------------------------------------------------------------------
# invoice.payment_succeeded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_succeeded_closes_deal() -> None:
    event = _make_invoice_event("invoice.payment_succeeded")

    with _valid_sig_patch() as mock_construct, patch(
        "app.api.v1.stripe_webhook._handle_payment_succeeded"
    ) as mock_handler:
        mock_handler.return_value = None
        mock_construct.return_value = event

        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/stripe",
                content=json.dumps(event).encode(),
                headers={"Stripe-Signature": "t=1,v1=valid"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["event_type"] == "invoice.payment_succeeded"


@pytest.mark.asyncio
async def test_payment_succeeded_calls_log_closed_deal() -> None:
    event_data = {
        "id": "in_test",
        "customer_email": "buyer@store.com",
        "amount_paid": 50000,
        "metadata": {
            "email_id": "550e8400-e29b-41d4-a716-446655440000",
            "tenant_id": "t1",
        },
    }
    mock_db = AsyncMock()
    mock_log = AsyncMock(return_value={"amount_usd": 500.0})

    with patch("app.api.v1.stripe_webhook.AsyncSessionLocal") as mock_ctx, patch(
        "app.api.v1.stripe_webhook.log_closed_deal", mock_log
    ):
        mock_ctx.return_value.__aenter__.return_value = mock_db
        mock_ctx.return_value.__aexit__.return_value = False

        from app.api.v1.stripe_webhook import _handle_payment_succeeded

        await _handle_payment_succeeded(event_data)

    mock_log.assert_awaited_once()
    call_kwargs = mock_log.call_args[1]
    assert call_kwargs["email_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert call_kwargs["invoice_id"] == "in_test"
    assert call_kwargs["amount_paid_cents"] == 50000
    assert call_kwargs["buyer_email"] == "buyer@store.com"


@pytest.mark.asyncio
async def test_payment_succeeded_skips_when_no_email_id() -> None:
    event_data = {"id": "in_test", "metadata": {}, "customer_email": "x@y.com", "amount_paid": 0}
    mock_log = AsyncMock()
    with patch("app.api.v1.stripe_webhook.log_closed_deal", mock_log):
        from app.api.v1.stripe_webhook import _handle_payment_succeeded

        await _handle_payment_succeeded(event_data)
    mock_log.assert_not_awaited()


# ---------------------------------------------------------------------------
# invoice.payment_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_failed_updates_deal_status() -> None:
    event_data = {
        "id": "in_test",
        "metadata": {"email_id": "550e8400-e29b-41d4-a716-446655440000"},
    }
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch("app.api.v1.stripe_webhook.AsyncSessionLocal") as mock_ctx:
        mock_ctx.return_value.__aenter__.return_value = mock_db
        mock_ctx.return_value.__aexit__.return_value = False

        from app.api.v1.stripe_webhook import _handle_payment_failed

        await _handle_payment_failed(event_data)

    mock_db.execute.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_failed_skips_when_no_email_id() -> None:
    event_data = {"id": "in_test", "metadata": {}}
    mock_db = AsyncMock()
    with patch("app.api.v1.stripe_webhook.AsyncSessionLocal") as mock_ctx:
        mock_ctx.return_value.__aenter__.return_value = mock_db
        mock_ctx.return_value.__aexit__.return_value = False

        from app.api.v1.stripe_webhook import _handle_payment_failed

        await _handle_payment_failed(event_data)

    mock_db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# invoice.marked_uncollectible (overdue)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoice_overdue_updates_deal_status() -> None:
    event_data = {
        "id": "in_test",
        "metadata": {"email_id": "550e8400-e29b-41d4-a716-446655440000"},
    }
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch("app.api.v1.stripe_webhook.AsyncSessionLocal") as mock_ctx:
        mock_ctx.return_value.__aenter__.return_value = mock_db
        mock_ctx.return_value.__aexit__.return_value = False

        from app.api.v1.stripe_webhook import _handle_invoice_overdue

        await _handle_invoice_overdue(event_data)

    mock_db.execute.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_invoice_overdue_skips_when_no_email_id() -> None:
    event_data = {"id": "in_test", "metadata": {}}
    mock_db = AsyncMock()
    with patch("app.api.v1.stripe_webhook.AsyncSessionLocal") as mock_ctx:
        mock_ctx.return_value.__aenter__.return_value = mock_db
        mock_ctx.return_value.__aexit__.return_value = False

        from app.api.v1.stripe_webhook import _handle_invoice_overdue

        await _handle_invoice_overdue(event_data)

    mock_db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Unhandled event type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhandled_event_returns_ok() -> None:
    event = _make_invoice_event("customer.created")
    with _valid_sig_patch() as mock_construct:
        mock_construct.return_value = event
        async with AsyncClient(
            transport=ASGITransport(app=_test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/webhooks/stripe",
                content=json.dumps(event).encode(),
                headers={"Stripe-Signature": "t=1,v1=valid"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
