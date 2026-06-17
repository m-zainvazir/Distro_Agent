"""Celery task: daily KPI digest sent via WhatsApp to each tenant."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from app.celery_app import celery_app
from app.core.logging import logger


def _format_kpi_digest(kpis: Any) -> str:
    """Compose a WhatsApp-friendly KPI summary."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"KPI Digest {date_str} (last {kpis.lookback_days}d)\n"
        f"Leads: {kpis.leads_discovered} discovered | {kpis.leads_qualified} qualified\n"
        f"Emails sent: {kpis.emails_sent}\n"
        f"Reply rate: {kpis.reply_rate:.1%} | Positive: {kpis.positive_reply_rate:.1%}\n"
        f"Meetings booked: {kpis.meetings_booked} | Booking rate: {kpis.booking_rate:.1%}\n"
        f"Deals closed: {kpis.deals_closed}\n"
        f"Cost: ${kpis.total_cost_usd:.2f} total | ${kpis.cost_per_lead:.4f}/lead"
    )


async def _run_metrics_digest() -> dict[str, Any]:
    """Compute per-tenant KPIs and send WhatsApp digest for all tenants with a phone."""
    from sqlalchemy.future import select

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.campaign import Tenant
    from app.services.metrics_service import compute_tenant_kpis
    from app.services.whatsapp_service import send_deal_alert

    tenants_notified = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tenant))
        tenants = result.scalars().all()

        for tenant in tenants:
            wa_num: str | None = tenant.whatsapp_number  # type: ignore[assignment]
            phone: str = wa_num or settings.whatsapp_founder_phone
            if not phone:
                continue

            try:
                kpis = await compute_tenant_kpis(
                    tenant_id=uuid.UUID(str(tenant.id)),
                    lookback_days=30,
                    db=db,
                )
                await send_deal_alert(
                    phone=phone,
                    store_name="DistroAgent KPIs",
                    reply_summary=_format_kpi_digest(kpis),
                )
                tenants_notified += 1
            except Exception as exc:
                logger.error(
                    "metrics_digest_tenant_failed",
                    tenant_id=str(tenant.id),
                    error=str(exc),
                )

    return {"tenants_notified": tenants_notified}


@celery_app.task(name="metrics.send_daily_digest")
def send_daily_kpi_digest() -> dict[str, Any]:
    """Compute per-tenant KPIs and send WhatsApp digest. Runs daily via Celery beat."""
    logger.info("metrics_task_started")
    result = asyncio.run(_run_metrics_digest())
    logger.info("metrics_task_complete", tenants_notified=result["tenants_notified"])
    return result
