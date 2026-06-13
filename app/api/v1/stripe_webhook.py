"""Stripe webhook handler.

POST /api/v1/webhooks/stripe

Handles:
  invoice.payment_succeeded    → close deal, CRM sync, notify founder
  invoice.payment_failed       → update deal_status to payment_failed
  invoice.marked_uncollectible → update deal_status to overdue

Security: Stripe-Signature header verified via stripe_webhook_secret.
Returns HTTP 200 on all routed events so Stripe does not retry.
"""
from __future__ import annotations

import uuid
from typing import Any

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.models.campaign import OutreachEmail
from app.services.crm_service import log_closed_deal
from app.services.stripe_service import construct_webhook_event

router = APIRouter(prefix="/webhooks", tags=["stripe"])


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def receive_stripe_webhook(request: Request) -> dict[str, str]:
    """Receive and route Stripe webhook events.

    Signature-verified via Stripe-Signature header + stripe_webhook_secret.
    Returns HTTP 200 on success so Stripe does not retry delivery.
    """
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except stripe.error.SignatureVerificationError:
        logger.warning("stripe_webhook_invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_SIGNATURE",
                "message": "Stripe signature verification failed",
            },
        )

    event_type: str = event["type"]
    data_object: dict[str, Any] = event["data"]["object"]
    logger.info("stripe_webhook_received", event_type=event_type, event_id=event["id"])

    try:
        if event_type == "invoice.payment_succeeded":
            await _handle_payment_succeeded(data_object)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(data_object)
        elif event_type == "invoice.marked_uncollectible":
            await _handle_invoice_overdue(data_object)
        else:
            logger.info("stripe_webhook_unhandled_event", event_type=event_type)
    except Exception as exc:
        logger.error("stripe_webhook_handler_error", event_type=event_type, error=str(exc))
        # Return 200 — Stripe retries on non-2xx, risking duplicate processing.
        return {"status": "error", "detail": str(exc)}

    return {"status": "ok", "event_type": event_type}


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


async def _handle_payment_succeeded(invoice: dict[str, Any]) -> None:
    invoice_id: str = invoice.get("id", "")
    email_id: str = invoice.get("metadata", {}).get("email_id", "")
    buyer_email: str = invoice.get("customer_email", "")
    amount_paid: int = int(invoice.get("amount_paid", 0))

    if not email_id:
        logger.warning("stripe_payment_no_email_id", invoice_id=invoice_id)
        return

    async with AsyncSessionLocal() as db:
        result = await log_closed_deal(
            db=db,
            email_id=email_id,
            invoice_id=invoice_id,
            amount_paid_cents=amount_paid,
            buyer_email=buyer_email,
        )

    logger.info(
        "stripe_deal_closed",
        email_id=email_id,
        invoice_id=invoice_id,
        amount_usd=result["amount_usd"],
    )


async def _handle_payment_failed(invoice: dict[str, Any]) -> None:
    invoice_id: str = invoice.get("id", "")
    email_id: str = invoice.get("metadata", {}).get("email_id", "")

    if not email_id:
        logger.warning("stripe_payment_failed_no_email_id", invoice_id=invoice_id)
        return

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutreachEmail)
            .where(OutreachEmail.id == uuid.UUID(email_id))
            .values(deal_status="payment_failed")
        )
        await db.commit()

    logger.warning("stripe_payment_failed", email_id=email_id, invoice_id=invoice_id)


async def _handle_invoice_overdue(invoice: dict[str, Any]) -> None:
    invoice_id: str = invoice.get("id", "")
    email_id: str = invoice.get("metadata", {}).get("email_id", "")

    if not email_id:
        logger.warning("stripe_invoice_overdue_no_email_id", invoice_id=invoice_id)
        return

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutreachEmail)
            .where(OutreachEmail.id == uuid.UUID(email_id))
            .values(deal_status="overdue")
        )
        await db.commit()

    logger.warning("stripe_invoice_overdue", email_id=email_id, invoice_id=invoice_id)
