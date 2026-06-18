"""Aggregate KPI metrics from existing tables — read-only, no new schema."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.campaign import OutreachEmail, StoreCandidate
from app.schemas.metrics import KpiSummary


async def compute_tenant_kpis(
    tenant_id: uuid.UUID,
    lookback_days: int = 30,
    *,
    db: AsyncSession,
) -> KpiSummary:
    """Aggregate distribution KPIs for *tenant_id* over the last *lookback_days* days."""
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).replace(tzinfo=None)

    # --- leads ---
    r = await db.execute(
        select(func.count()).select_from(StoreCandidate).where(
            StoreCandidate.tenant_id == tenant_id,
            StoreCandidate.created_at >= since,
        )
    )
    leads_discovered: int = r.scalar_one() or 0

    r = await db.execute(
        select(func.count()).select_from(StoreCandidate).where(
            StoreCandidate.tenant_id == tenant_id,
            StoreCandidate.created_at >= since,
            StoreCandidate.status == "qualified",
        )
    )
    leads_qualified: int = r.scalar_one() or 0

    # --- outreach emails ---
    r = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            OutreachEmail.tenant_id == tenant_id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= since,
        )
    )
    emails_sent: int = r.scalar_one() or 0

    r = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            OutreachEmail.tenant_id == tenant_id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= since,
            OutreachEmail.reply_received.is_(True),
        )
    )
    replies: int = r.scalar_one() or 0

    r = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            OutreachEmail.tenant_id == tenant_id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= since,
            OutreachEmail.reply_intent.in_(["INTERESTED", "MEETING_REQUEST"]),
        )
    )
    positive_replies: int = r.scalar_one() or 0

    r = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            OutreachEmail.tenant_id == tenant_id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= since,
            OutreachEmail.reply_intent == "MEETING_REQUEST",
        )
    )
    meetings_booked: int = r.scalar_one() or 0

    r = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            OutreachEmail.tenant_id == tenant_id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= since,
            OutreachEmail.outcome == "deal_closed",
        )
    )
    deals_closed: int = r.scalar_one() or 0

    # --- derived rates (guarded against division-by-zero) ---
    reply_rate = replies / emails_sent if emails_sent else 0.0
    positive_reply_rate = positive_replies / emails_sent if emails_sent else 0.0
    booking_rate = meetings_booked / emails_sent if emails_sent else 0.0

    # token cost is logged as structured events, not persisted in DB — defaults to 0.0
    total_cost_usd = 0.0
    cost_per_lead = total_cost_usd / leads_discovered if leads_discovered else 0.0

    logger.info(
        "metrics_kpis_computed",
        tenant_id=str(tenant_id),
        lookback_days=lookback_days,
        emails_sent=emails_sent,
        reply_rate=round(reply_rate, 4),
    )

    return KpiSummary(
        leads_discovered=leads_discovered,
        leads_qualified=leads_qualified,
        emails_sent=emails_sent,
        reply_rate=round(reply_rate, 4),
        positive_reply_rate=round(positive_reply_rate, 4),
        meetings_booked=meetings_booked,
        booking_rate=round(booking_rate, 4),
        deals_closed=deals_closed,
        total_cost_usd=total_cost_usd,
        cost_per_lead=cost_per_lead,
        lookback_days=lookback_days,
        generated_at=datetime.now(timezone.utc),
    )
