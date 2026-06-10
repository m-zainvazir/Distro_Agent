"""Secondary sending domain management + warmup schedule.

Deliverability shield rules
---------------------------
- Tenants NEVER send from their primary brand domain.
- Each tenant owns ≥1 secondary sending domain (e.g. trybrandname.com).
- New domains follow a 14-day warmup ramp before hitting 100 emails/day.
- If bounce rate exceeds 5%, the domain is paused automatically.

DNS records to configure per secondary domain
----------------------------------------------
SPF:   <domain>              TXT    "v=spf1 include:sendgrid.net ~all"
DKIM:  s1._domainkey.<domain> CNAME s1.domainkey.u<uid>.wl.sendgrid.net
       s2._domainkey.<domain> CNAME s2.domainkey.u<uid>.wl.sendgrid.net
DMARC: _dmarc.<domain>       TXT   "v=DMARC1; p=quarantine; rua=mailto:dmarc@<domain>"
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.logging import logger
from app.models.sending_domain import SendingDomain

_WARMUP_DAYS = 14
_DAILY_CAP_MAX = 100
_BOUNCE_RATE_THRESHOLD = 0.05


def daily_send_limit(domain: SendingDomain) -> int:
    """Linear warmup ramp: 10 on day 1, reaching 100 on day 14."""
    day = max(1, min(domain.warmup_day, _WARMUP_DAYS))
    ramp = (_DAILY_CAP_MAX - 10) * (day - 1) // (_WARMUP_DAYS - 1)
    return min(10 + ramp, _DAILY_CAP_MAX)


async def get_active_domain(
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> SendingDomain | None:
    """Return the first non-paused active sending domain for a tenant."""
    result = await db.execute(
        select(SendingDomain).where(
            SendingDomain.tenant_id == tenant_id,
            SendingDomain.is_active.is_(True),
            SendingDomain.paused.is_(False),
        )
    )
    return result.scalars().first()


async def record_send(domain: SendingDomain, db: AsyncSession) -> None:
    """Increment today's send count and advance warmup day on a new calendar day."""
    today = date.today()
    if domain.last_send_date != today:
        domain.emails_sent_today = 0
        domain.last_send_date = today
        if domain.warmup_day < _WARMUP_DAYS:
            domain.warmup_day += 1
    domain.emails_sent_today += 1
    domain.send_count += 1
    await db.commit()
    logger.info(
        "domain_send_recorded",
        domain=domain.domain,
        today_count=domain.emails_sent_today,
        warmup_day=domain.warmup_day,
    )


async def record_bounce(domain: SendingDomain, db: AsyncSession) -> None:
    """Increment bounce count and pause the domain if rate exceeds threshold."""
    domain.bounce_count += 1
    if domain.send_count > 0:
        rate = domain.bounce_count / domain.send_count
        if rate > _BOUNCE_RATE_THRESHOLD:
            domain.paused = True
            domain.paused_reason = (
                f"Bounce rate {rate:.1%} exceeded "
                f"{_BOUNCE_RATE_THRESHOLD:.0%} threshold"
            )
            logger.warning(
                "domain_paused_high_bounce_rate",
                domain=domain.domain,
                bounce_rate=rate,
            )
    await db.commit()
