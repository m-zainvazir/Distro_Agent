"""Celery task: pick up approved OutreachEmails and send them every 15 minutes."""
from __future__ import annotations

import asyncio

from app.celery_app import celery_app
from app.core.logging import logger


async def _send_approved_emails() -> dict:
    """Async core — query all approved emails and send each within daily cap."""
    from sqlalchemy.future import select

    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail
    from app.services.email_service import (
        DailySendCapExceeded,
        NoDomainConfigured,
        send_outreach_email,
    )

    sent = 0
    skipped = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OutreachEmail).where(OutreachEmail.outcome == "approved")
        )
        emails = result.scalars().all()

        for email in emails:
            try:
                await send_outreach_email(email, db)
                sent += 1
            except DailySendCapExceeded:
                skipped += 1
                break  # daily cap hit — stop processing this run
            except NoDomainConfigured:
                skipped += 1
            except Exception as exc:
                errors += 1
                logger.error(
                    "email_task_send_error",
                    email_id=str(email.id),
                    error=str(exc),
                )

    return {"sent": sent, "skipped": skipped, "errors": errors}


@celery_app.task(name="email.send_approved")
def send_approved_emails_task() -> dict:
    """Send all approved outreach emails, respecting per-tenant daily caps.

    Scheduled every 15 minutes via Celery beat.
    """
    logger.info("email_task_started")
    result = asyncio.run(_send_approved_emails())
    logger.info("email_task_complete", **result)
    return result
