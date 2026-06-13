"""Celery task: generate draft Stripe invoice, gate with admin approval, then send.

Flow:
  1. Create Stripe draft invoice + persist invoice_id on OutreachEmail (async)
  2. require_admin_approval("send_invoice", ...) — blocks thread up to 1 hour
  3. Admin approves → finalize + send invoice, set deal_status="invoice_sent" (async)
  4. Admin rejects  → set deal_status="invoice_rejected", return skipped

Dispatched by negotiator_agent.finalize_node when a counter-offer is approved.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import update

from app.celery_app import celery_app
from app.core.governance import require_admin_approval
from app.core.logging import logger


# ---------------------------------------------------------------------------
# Async helpers (each called via asyncio.run — no nesting)
# ---------------------------------------------------------------------------


async def _create_and_persist(
    email_id: str,
    buyer_email: str,
    buyer_name: str,
    line_items: list[dict],
    due_days: int,
    agreed_terms: str,
    tenant_id: str,
) -> str:
    """Create Stripe draft, persist invoice_id, return invoice_id."""
    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail
    from app.services.stripe_service import create_invoice

    invoice_id = await create_invoice(
        customer_email=buyer_email,
        customer_name=buyer_name or buyer_email,
        line_items=line_items,
        due_days=due_days,
        metadata={
            "email_id": email_id,
            "tenant_id": tenant_id,
            "agreed_terms": agreed_terms[:500],
        },
    )

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutreachEmail)
            .where(OutreachEmail.id == uuid.UUID(email_id))
            .values(stripe_invoice_id=invoice_id, deal_status="invoice_pending")
        )
        await db.commit()

    return invoice_id


async def _send_and_update(email_id: str, invoice_id: str) -> str:
    """Send invoice, update deal_status to invoice_sent. Returns hosted_invoice_url."""
    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail
    from app.services.stripe_service import send_invoice

    url = await send_invoice(invoice_id)

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutreachEmail)
            .where(OutreachEmail.id == uuid.UUID(email_id))
            .values(deal_status="invoice_sent", outcome="invoice_sent")
        )
        await db.commit()

    return url


async def _mark_status(email_id: str, deal_status: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutreachEmail)
            .where(OutreachEmail.id == uuid.UUID(email_id))
            .values(deal_status=deal_status)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(name="invoice.generate_and_send")
def generate_and_send_invoice_task(
    email_id: str,
    tenant_id: str,
    buyer_email: str,
    buyer_name: str,
    line_items: list[dict],
    due_days: int,
    agreed_terms: str,
) -> dict[str, Any]:
    """Generate a draft invoice, await admin approval, then send to buyer.

    Blocking governance gate: waits up to 1 hour for admin click.
    Only dispatch from Celery — never from an async event loop.
    """
    logger.info("invoice_task_started", email_id=email_id, buyer_email=buyer_email)

    # Step 1: Create draft + persist
    try:
        invoice_id = asyncio.run(
            _create_and_persist(
                email_id=email_id,
                buyer_email=buyer_email,
                buyer_name=buyer_name,
                line_items=line_items,
                due_days=due_days,
                agreed_terms=agreed_terms,
                tenant_id=tenant_id,
            )
        )
    except Exception as exc:
        logger.error("invoice_create_failed", email_id=email_id, error=str(exc))
        return {"status": "error", "reason": str(exc)}

    # Step 2: Admin approval gate
    amount_usd = sum(i.get("amount_cents", 0) for i in line_items) / 100
    approved = require_admin_approval(
        action_type="send_invoice",
        payload={
            "invoice_id": invoice_id,
            "email_id": email_id,
            "buyer_email": buyer_email,
            "amount_usd": amount_usd,
            "line_items": line_items,
            "agreed_terms": agreed_terms[:300],
        },
    )

    if not approved:
        asyncio.run(_mark_status(email_id, "invoice_rejected"))
        logger.info("invoice_task_rejected", email_id=email_id, invoice_id=invoice_id)
        return {
            "status": "skipped",
            "reason": "admin_rejected_or_timed_out",
            "invoice_id": invoice_id,
        }

    # Step 3: Send invoice
    try:
        url = asyncio.run(_send_and_update(email_id, invoice_id))
    except Exception as exc:
        logger.error("invoice_send_failed", invoice_id=invoice_id, error=str(exc))
        asyncio.run(_mark_status(email_id, "send_failed"))
        return {"status": "error", "reason": str(exc), "invoice_id": invoice_id}

    logger.info(
        "invoice_task_complete",
        email_id=email_id,
        invoice_id=invoice_id,
        url=url,
    )
    return {"status": "sent", "invoice_id": invoice_id, "invoice_url": url}
