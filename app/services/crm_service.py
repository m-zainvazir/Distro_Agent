"""CRM sync — update deal state in Postgres and notify founder via WhatsApp.

Called after Stripe payment.succeeded. Marks the store as "converted",
updates the email outcome to "deal_closed", and sends a WhatsApp summary
to the founder.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger


async def log_closed_deal(
    db: AsyncSession,
    email_id: str,
    invoice_id: str,
    amount_paid_cents: int,
    buyer_email: str,
) -> dict[str, Any]:
    """Mark email as deal_closed, store as converted, notify founder.

    Returns a summary dict with email_id, invoice_id, amount_usd, status.
    """
    from app.models.campaign import OutreachEmail, StoreCandidate

    await db.execute(
        update(OutreachEmail)
        .where(OutreachEmail.id == uuid.UUID(email_id))
        .values(outcome="deal_closed", deal_status="deal_closed", stripe_invoice_id=invoice_id)
    )

    # Fetch store_id and tenant_id so we can mark the store converted and push CRM event
    result = await db.execute(
        select(OutreachEmail.store_id, OutreachEmail.tenant_id).where(
            OutreachEmail.id == uuid.UUID(email_id)
        )
    )
    row = result.first()
    tenant_id_str: str = str(row.tenant_id) if row and row.tenant_id else ""
    if row and row.store_id:
        await db.execute(
            update(StoreCandidate)
            .where(StoreCandidate.id == row.store_id)
            .values(status="converted")
        )

    await db.commit()

    amount_usd = amount_paid_cents / 100
    logger.info(
        "crm_deal_closed",
        email_id=email_id,
        invoice_id=invoice_id,
        amount_usd=amount_usd,
        buyer_email=buyer_email,
    )

    # Push to tenant CRM
    try:
        from app.services.crm_sync import CrmEventType, push_event

        await push_event(
            tenant_id=tenant_id_str,
            event_type=CrmEventType.DEAL_CLOSED,
            event_data={
                "store_email": buyer_email,
                "invoice_id": invoice_id,
                "amount_usd": amount_usd,
                "email_id": email_id,
            },
            db=db,
        )
    except Exception as exc:
        logger.warning("crm_sync_deal_closed_failed", error=str(exc))

    if settings.whatsapp_founder_phone:
        try:
            from app.services.whatsapp_service import send_deal_alert

            await send_deal_alert(
                phone=settings.whatsapp_founder_phone,
                store_name=buyer_email,
                reply_summary=(
                    f"Deal closed! Payment received\n"
                    f"Buyer: {buyer_email}\n"
                    f"Amount: ${amount_usd:,.2f}\n"
                    f"Invoice: {invoice_id}"
                ),
            )
        except Exception as exc:
            logger.warning("crm_whatsapp_notify_failed", error=str(exc))

    return {
        "email_id": email_id,
        "invoice_id": invoice_id,
        "amount_usd": amount_usd,
        "status": "deal_closed",
    }
