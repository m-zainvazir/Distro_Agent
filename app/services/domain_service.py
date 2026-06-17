"""Secondary sending domain management + warmup schedule.

Deliverability shield rules
---------------------------
- Tenants NEVER send from their primary brand domain.
- Each tenant owns ≥1 secondary sending domain (e.g. trybrandname.com).
- New domains follow a 14-day warmup ramp before hitting 100 emails/day.
- If bounce rate exceeds 5%, the domain is paused automatically.

DNS records configured per secondary domain (SPF/DKIM/DMARC)
-------------------------------------------------------------
SPF:   <domain>               TXT   "v=spf1 include:sendgrid.net ~all"
DKIM:  s1._domainkey.<domain> CNAME s1.domainkey.u<uid>.wl.sendgrid.net
       s2._domainkey.<domain> CNAME s2.domainkey.u<uid>.wl.sendgrid.net
DMARC: _dmarc.<domain>        TXT   "v=DMARC1; p=none; ..." (starts at p=none, ramp to quarantine after warm-up)
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.core.logging import logger
from app.models.sending_domain import SendingDomain
from app.tools.domain_registrar import CloudflareDNSClient, DomainRegistrarError

_WARMUP_DAYS = 14
_DAILY_CAP_MAX = 100
_BOUNCE_RATE_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Warm-up ramp (existing logic — unchanged)
# ---------------------------------------------------------------------------


def daily_send_limit(domain: SendingDomain) -> int:
    """Linear warmup ramp: 10 on day 1, reaching 100 on day 14."""
    day: int = max(1, min(int(domain.warmup_day), _WARMUP_DAYS))  # type: ignore[arg-type]
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
        domain.emails_sent_today = 0  # type: ignore[assignment]
        domain.last_send_date = today  # type: ignore[assignment]
        if domain.warmup_day < _WARMUP_DAYS:
            domain.warmup_day += 1  # type: ignore[assignment]
    domain.emails_sent_today += 1  # type: ignore[assignment]
    domain.send_count += 1  # type: ignore[assignment]
    await db.commit()
    logger.info(
        "domain_send_recorded",
        domain=domain.domain,
        today_count=domain.emails_sent_today,
        warmup_day=domain.warmup_day,
    )


async def record_bounce(domain: SendingDomain, db: AsyncSession) -> None:
    """Increment bounce count and pause the domain if rate exceeds threshold."""
    domain.bounce_count += 1  # type: ignore[assignment]
    if domain.send_count > 0:
        rate = domain.bounce_count / domain.send_count  # type: ignore[operator]
        if rate > _BOUNCE_RATE_THRESHOLD:
            domain.paused = True  # type: ignore[assignment]
            reason = (
                f"Bounce rate {rate:.1%} exceeded "
                f"{_BOUNCE_RATE_THRESHOLD:.0%} threshold"
            )
            domain.paused_reason = reason  # type: ignore[assignment]
            logger.warning(
                "domain_paused_high_bounce_rate",
                domain=domain.domain,
                bounce_rate=rate,
            )
    await db.commit()


# ---------------------------------------------------------------------------
# Domain provisioning (Layer 20 — new)
# ---------------------------------------------------------------------------


def _generate_domain_candidates(brand_name: str) -> list[str]:
    """Produce secondary domain candidates from settings templates.

    Templates use ``{brand}`` as a placeholder for the slugified brand name.
    """
    slug = re.sub(r"[^a-z0-9]", "", brand_name.lower())
    templates = [t.strip() for t in settings.domain_name_templates.split(",") if t.strip()]
    return [t.replace("{brand}", slug) for t in templates]


def _guard_primary_domain(secondary: str, brand_name: str) -> None:
    """Raise ValueError if *secondary* matches the brand's inferred primary domain.

    The brand's primary domain is inferred as ``<slug>.com`` — tenants must
    NEVER send outreach from their own brand domain.
    """
    slug = re.sub(r"[^a-z0-9]", "", brand_name.lower())
    if secondary == f"{slug}.com":
        raise ValueError(
            f"Cannot use primary domain {secondary!r} as a sending domain — "
            "outreach must originate from a secondary domain only."
        )


async def _configure_dns_records(
    client: CloudflareDNSClient,
    zone_id: str,
    domain: str,
) -> None:
    """Write SPF, DKIM (×2), and DMARC=p=none records via Cloudflare."""
    # SPF
    await client.create_dns_record(
        zone_id, "TXT", domain, "v=spf1 include:sendgrid.net ~all"
    )

    # DKIM — two CNAME records required by SendGrid domain authentication
    uid = settings.sendgrid_domain_auth_uid
    if uid:
        await client.create_dns_record(
            zone_id,
            "CNAME",
            f"s1._domainkey.{domain}",
            f"s1.domainkey.u{uid}.wl.sendgrid.net",
        )
        await client.create_dns_record(
            zone_id,
            "CNAME",
            f"s2._domainkey.{domain}",
            f"s2.domainkey.u{uid}.wl.sendgrid.net",
        )

    # DMARC — always start at p=none; ramp to quarantine after warm-up proves clean
    await client.create_dns_record(
        zone_id,
        "TXT",
        f"_dmarc.{domain}",
        f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}",
    )


async def _verify_spf_propagated(
    client: CloudflareDNSClient,
    zone_id: str,
    domain: str,
) -> bool:
    """Check if the SPF TXT record is visible via the Cloudflare DNS API."""
    records = await client.get_dns_records(zone_id, "TXT", domain)
    return any("v=spf1" in r.get("content", "") for r in records)


async def provision_sending_domain(
    tenant_id: uuid.UUID,
    brand_name: str,
    db: AsyncSession,
) -> SendingDomain:
    """Register a secondary sending domain and configure SPF/DKIM/DMARC.

    Flow:
    1. Generate domain candidates from ``settings.domain_name_templates``.
    2. For each candidate, ensure a Cloudflare zone exists (get or create).
    3. Write SPF / DKIM / DMARC records (DMARC starts at p=none).
    4. Attempt immediate DNS verification (Cloudflare sees its own records instantly).
    5. Persist a ``SendingDomain`` row in warmup-day-1 state and hand off to
       the existing warmup ramp + bounce-pause logic.

    The brand's inferred primary domain is never used (guard enforced).
    """
    candidates = _generate_domain_candidates(brand_name)
    client = CloudflareDNSClient()

    zone_id: str | None = None
    chosen: str | None = None

    for candidate in candidates:
        try:
            _guard_primary_domain(candidate, brand_name)
        except ValueError as exc:
            logger.warning("domain_primary_domain_skipped", domain=candidate, reason=str(exc))
            continue

        try:
            zone_id = await client.ensure_zone(candidate)
            chosen = candidate
            break
        except DomainRegistrarError as exc:
            logger.warning("domain_zone_failed", domain=candidate, error=str(exc))

    if not zone_id or not chosen:
        raise DomainRegistrarError(
            f"Could not provision a secondary sending domain for brand '{brand_name}'. "
            "Check Cloudflare credentials and DNS settings."
        )

    await _configure_dns_records(client, zone_id, chosen)

    dns_verified = await _verify_spf_propagated(client, zone_id, chosen)
    now = datetime.now(timezone.utc)

    domain_row = SendingDomain(
        tenant_id=tenant_id,
        domain=chosen,
        is_active=True,
        warmup_day=1,
        provisioning_status="dns_verified" if dns_verified else "dns_configured",
        dns_verified_at=now if dns_verified else None,
    )
    db.add(domain_row)
    await db.commit()
    await db.refresh(domain_row)

    logger.info(
        "sending_domain_provisioned",
        tenant_id=str(tenant_id),
        domain=chosen,
        dns_verified=dns_verified,
    )
    return domain_row
