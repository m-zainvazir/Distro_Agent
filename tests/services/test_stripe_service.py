"""Tests for app/services/stripe_service.py — all Stripe SDK calls mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import stripe

from app.services.stripe_service import (
    _create_invoice_sync,
    _get_or_create_customer,
    _send_invoice_sync,
    construct_webhook_event,
    create_invoice,
    send_invoice,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    existing_customers: list | None = None,
    invoice_id: str = "in_test123",
    invoice_url: str = "https://invoice.stripe.com/i/in_test123",
) -> MagicMock:
    client = MagicMock()
    client.customers.list.return_value.data = existing_customers or []
    client.customers.create.return_value.id = "cus_new"
    client.invoice_items.create.return_value = MagicMock()
    client.invoices.create.return_value.id = invoice_id
    client.invoices.finalize_invoice.return_value = MagicMock()
    client.invoices.send_invoice.return_value.hosted_invoice_url = invoice_url
    return client


# ---------------------------------------------------------------------------
# _get_or_create_customer
# ---------------------------------------------------------------------------


def test_get_or_create_customer_creates_new() -> None:
    client = _make_client()
    cid = _get_or_create_customer(client, "buyer@store.com", "Brooklyn Boutique")
    assert cid == "cus_new"
    client.customers.create.assert_called_once()


def test_get_or_create_customer_reuses_existing() -> None:
    existing = MagicMock()
    existing.id = "cus_existing"
    client = _make_client(existing_customers=[existing])
    cid = _get_or_create_customer(client, "buyer@store.com", "Brooklyn Boutique")
    assert cid == "cus_existing"
    client.customers.create.assert_not_called()


# ---------------------------------------------------------------------------
# _create_invoice_sync
# ---------------------------------------------------------------------------


def test_create_invoice_sync_new_customer() -> None:
    client = _make_client()
    with patch("app.services.stripe_service._client", return_value=client):
        invoice_id = _create_invoice_sync(
            customer_email="buyer@store.com",
            customer_name="Buyer",
            line_items=[{"description": "Wholesale order", "amount_cents": 50000}],
            due_days=30,
            metadata={"email_id": "abc-123"},
        )
    assert invoice_id == "in_test123"
    client.invoice_items.create.assert_called_once()
    client.invoices.create.assert_called_once()


def test_create_invoice_sync_multiple_line_items() -> None:
    client = _make_client()
    with patch("app.services.stripe_service._client", return_value=client):
        _create_invoice_sync(
            customer_email="buyer@store.com",
            customer_name="Buyer",
            line_items=[
                {"description": "Item A", "amount_cents": 10000},
                {"description": "Item B", "amount_cents": 20000},
            ],
            due_days=15,
            metadata={},
        )
    assert client.invoice_items.create.call_count == 2


def test_create_invoice_sync_no_line_items() -> None:
    client = _make_client()
    with patch("app.services.stripe_service._client", return_value=client):
        invoice_id = _create_invoice_sync(
            customer_email="buyer@store.com",
            customer_name="",
            line_items=[],
            due_days=30,
            metadata={},
        )
    assert invoice_id == "in_test123"
    client.invoice_items.create.assert_not_called()


def test_create_invoice_sync_enforces_min_due_days() -> None:
    client = _make_client()
    with patch("app.services.stripe_service._client", return_value=client):
        _create_invoice_sync("e@b.com", "name", [], due_days=0, metadata={})
    call_kwargs = client.invoices.create.call_args[1]["params"]
    assert call_kwargs["days_until_due"] >= 1


def test_create_invoice_sync_reuses_existing_customer() -> None:
    existing = MagicMock()
    existing.id = "cus_existing"
    client = _make_client(existing_customers=[existing])
    with patch("app.services.stripe_service._client", return_value=client):
        _create_invoice_sync("e@b.com", "name", [], 30, {})
    client.customers.create.assert_not_called()


# ---------------------------------------------------------------------------
# _send_invoice_sync
# ---------------------------------------------------------------------------


def test_send_invoice_sync_finalizes_then_sends() -> None:
    client = _make_client()
    with patch("app.services.stripe_service._client", return_value=client):
        url = _send_invoice_sync("in_test123")
    assert url == "https://invoice.stripe.com/i/in_test123"
    client.invoices.finalize_invoice.assert_called_once_with("in_test123")
    client.invoices.send_invoice.assert_called_once_with("in_test123")


def test_send_invoice_sync_returns_empty_string_when_no_url() -> None:
    client = _make_client()
    client.invoices.send_invoice.return_value.hosted_invoice_url = None
    with patch("app.services.stripe_service._client", return_value=client):
        url = _send_invoice_sync("in_test123")
    assert url == ""


# ---------------------------------------------------------------------------
# Async wrappers (patch the sync cores)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invoice_delegates_to_sync() -> None:
    with patch("app.services.stripe_service._create_invoice_sync", return_value="in_async") as mock:
        result = await create_invoice(
            customer_email="b@s.com",
            customer_name="Buyer",
            line_items=[{"description": "Item", "amount_cents": 5000}],
        )
    assert result == "in_async"
    mock.assert_called_once()


@pytest.mark.asyncio
async def test_send_invoice_delegates_to_sync() -> None:
    with patch("app.services.stripe_service._send_invoice_sync", return_value="https://url") as mock:
        url = await send_invoice("in_test123")
    assert url == "https://url"
    mock.assert_called_once_with("in_test123")


# ---------------------------------------------------------------------------
# construct_webhook_event
# ---------------------------------------------------------------------------


def test_construct_webhook_event_raises_on_bad_signature() -> None:
    with patch("app.services.stripe_service.stripe.Webhook.construct_event") as mock:
        mock.side_effect = stripe.error.SignatureVerificationError(
            "bad", sig_header="t=1,v1=bad"
        )
        with pytest.raises(stripe.error.SignatureVerificationError):
            construct_webhook_event(b"payload", "t=1,v1=bad")


def test_construct_webhook_event_returns_event_on_valid_sig() -> None:
    fake_event = {"type": "invoice.payment_succeeded", "id": "evt_123", "data": {}}
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=fake_event):
        result = construct_webhook_event(b"payload", "t=valid,v1=abc")
    assert result["type"] == "invoice.payment_succeeded"
