"""Stripe invoice service — create draft invoices and deliver them to buyers.

Stripe SDK calls are synchronous; all public coroutines delegate to the
default thread-pool executor so they don't block the FastAPI event loop.
"""
from __future__ import annotations

import asyncio
from typing import Any

import stripe
from stripe import StripeClient

from app.core.config import settings
from app.core.logging import logger

# keys: description (str), amount_cents (int)
LineItem = dict[str, Any]


def _client() -> StripeClient:
    return StripeClient(settings.stripe_secret_key)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


def _get_or_create_customer(client: StripeClient, email: str, name: str) -> str:
    existing = client.customers.list(params={"email": email, "limit": 1})
    if existing.data:
        cid: str = existing.data[0].id
        logger.info("stripe_customer_reused", customer_id=cid)
        return cid
    cust = client.customers.create(params={"email": email, "name": name or email})
    logger.info("stripe_customer_created", customer_id=cust.id)
    return str(cust.id)


# ---------------------------------------------------------------------------
# Create draft invoice (synchronous core — runs in executor)
# ---------------------------------------------------------------------------


def _create_invoice_sync(
    customer_email: str,
    customer_name: str,
    line_items: list[LineItem],
    due_days: int,
    metadata: dict[str, str],
) -> str:
    client = _client()
    customer_id = _get_or_create_customer(client, customer_email, customer_name)

    for item in line_items:
        client.invoice_items.create(
            params={
                "customer": customer_id,
                "amount": int(item["amount_cents"]),
                "currency": "usd",
                "description": item["description"],
            }
        )

    invoice = client.invoices.create(
        params={
            "customer": customer_id,
            "collection_method": "send_invoice",
            "days_until_due": max(1, due_days),
            "metadata": metadata,
            "auto_advance": False,  # keep as draft until explicitly finalized
        }
    )
    return str(invoice.id)


async def create_invoice(
    customer_email: str,
    customer_name: str,
    line_items: list[LineItem],
    due_days: int = 30,
    metadata: dict[str, str] | None = None,
) -> str:
    """Create a Stripe draft invoice. Returns invoice_id."""
    loop = asyncio.get_running_loop()
    invoice_id: str = await loop.run_in_executor(
        None,
        lambda: _create_invoice_sync(
            customer_email, customer_name, line_items, due_days, metadata or {}
        ),
    )
    logger.info("stripe_invoice_created", invoice_id=invoice_id, email=customer_email)
    return invoice_id


# ---------------------------------------------------------------------------
# Finalize and send (synchronous core)
# ---------------------------------------------------------------------------


def _send_invoice_sync(invoice_id: str) -> str:
    client = _client()
    client.invoices.finalize_invoice(invoice_id)
    sent = client.invoices.send_invoice(invoice_id)
    return str(sent.hosted_invoice_url or "")


async def send_invoice(invoice_id: str) -> str:
    """Finalize and email the invoice to the customer. Returns hosted_invoice_url."""
    loop = asyncio.get_running_loop()
    url: str = await loop.run_in_executor(
        None, lambda: _send_invoice_sync(invoice_id)
    )
    logger.info("stripe_invoice_sent", invoice_id=invoice_id, url=url)
    return url


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Construct and verify a Stripe webhook event from raw bytes.

    Raises stripe.error.SignatureVerificationError on bad signatures.
    """
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
