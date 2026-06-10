"""Email delivery — sends approved OutreachEmails via SendGrid.

PRECONDITION: Only emails with outcome == "approved" may be sent.
The assert in send_outreach_email enforces this; callers must never bypass it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.core.logging import logger
from app.models.campaign import OutreachCampaign, OutreachEmail
from app.services.domain_service import (
    daily_send_limit,
    get_active_domain,
    record_send,
)

_SENDGRID_API = "https://api.sendgrid.com/v3/mail/send"
_APPROVED = "approved"
_SENT = "sent"


class DailySendCapExceeded(Exception):
    """Tenant domain has reached its daily send limit."""


class NoDomainConfigured(Exception):
    """No active sending domain is configured for this tenant."""


def _sendgrid_payload(
    to_email: str,
    from_email: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    return {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": True},
        },
    }


async def send_outreach_email(
    email: OutreachEmail,
    db: AsyncSession,
) -> None:
    """Send a single approved outreach email via SendGrid.

    Raises:
        AssertionError: If email.outcome is not "approved".
        NoDomainConfigured: If the tenant has no active sending domain.
        DailySendCapExceeded: If the domain's warmup cap is reached for today.
        RuntimeError: If SendGrid returns a non-2xx status.
    """
    assert email.outcome == _APPROVED, (
        f"send_outreach_email requires outcome=='approved', got {email.outcome!r}"
    )

    camp_res = await db.execute(
        select(OutreachCampaign).where(OutreachCampaign.id == email.campaign_id)
    )
    campaign = camp_res.scalar_one_or_none()
    if campaign is None:
        raise ValueError(f"Campaign {email.campaign_id} not found")

    tenant_id: uuid.UUID = campaign.tenant_id

    domain = await get_active_domain(tenant_id, db)
    if domain is None:
        raise NoDomainConfigured(
            f"No active sending domain for tenant {tenant_id}"
        )

    cap = daily_send_limit(domain)
    if domain.emails_sent_today >= cap:
        raise DailySendCapExceeded(
            f"Daily cap {cap} reached for domain {domain.domain}"
        )

    to_email: str = getattr(email, "to_email", None) or ""
    if not to_email:
        raise ValueError(f"OutreachEmail {email.id} has no recipient address")

    payload = _sendgrid_payload(
        to_email=to_email,
        from_email=f"hello@{domain.domain}",
        subject=email.subject,
        body=email.body,
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _SENDGRID_API,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code not in (200, 202):
        logger.error(
            "sendgrid_send_failed",
            email_id=str(email.id),
            status_code=resp.status_code,
        )
        raise RuntimeError(f"SendGrid returned {resp.status_code}")

    message_id: str = resp.headers.get("X-Message-Id", "")
    email.outcome = _SENT
    email.sent_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    email.message_id = message_id  # type: ignore[attr-defined]
    await db.commit()

    await record_send(domain, db)
    logger.info(
        "outreach_email_sent",
        email_id=str(email.id),
        domain=domain.domain,
        message_id=message_id,
    )
