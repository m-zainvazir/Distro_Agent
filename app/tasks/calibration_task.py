"""Celery task: daily scoring weight calibration from last 30 days of outcome data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.celery_app import celery_app
from app.core.logging import logger


def _format_report(reports: list[dict[str, Any]]) -> str:
    """Compose a WhatsApp-friendly performance summary."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"Scoring Calibration Report {date_str}"]

    for r in reports:
        lines.append(f"\nVertical: {r['vertical_tag']}")
        lines.append(
            f"Emails: {r['total_emails']} | "
            f"Wins: {r['wins']} | "
            f"Losses: {r['losses']} | "
            f"Neutral: {r['neutral']}"
        )
        lines.append(f"Conversion rate: {r['conversion_rate_pct']}%")
        lines.append(f"Visual correlation: {r['visual_correlation']}")
        lines.append("Win rate by vibe score:")
        for bucket, rate_str in r["bucket_win_rates"].items():
            lines.append(f"  {bucket}: {rate_str}")

        if r["weights_updated"]:
            lines.append(
                f"Visual weight updated: "
                f"{r['old_visual_weight']} -> {r['new_visual_weight']}"
            )
        elif r.get("weights_gate_rejected"):
            lines.append(
                f"Visual weight update REJECTED by admin "
                f"(kept {r['old_visual_weight']})"
            )
        else:
            lines.append(
                f"Weights unchanged "
                f"(sample={r['sample_size']}, r={r['visual_correlation']})"
            )

    return "\n".join(lines)


async def _run_calibration() -> dict[str, Any]:
    """Core async logic: calibrate per-vertical, then notify admin via WhatsApp."""
    from sqlalchemy.future import select

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.core.governance import _admin_phone, require_admin_approval
    from app.models.campaign import OutreachCampaign
    from app.services.calibration_service import calibrate_weights
    from app.services.whatsapp_service import send_deal_alert

    # The weight-update gate is unbypassable only when an admin can actually
    # approve it. With no admin phone configured the governance wait would block
    # for the full timeout and never resolve, so calibration stays autonomous.
    gate = require_admin_approval if _admin_phone() else None
    if gate is None:
        logger.warning("calibration_gate_disabled_no_admin_phone")

    async with AsyncSessionLocal() as db:
        # Discover all distinct verticals with active campaigns
        result = await db.execute(
            select(OutreachCampaign.vertical_tag).distinct()
        )
        verticals: list[str] = [r for (r,) in result.all() if r]
        # Always include the global "all" fallback
        if "all" not in verticals:
            verticals.append("all")

        reports: list[dict[str, Any]] = []
        for vertical in verticals:
            try:
                report = await calibrate_weights(
                    vertical_tag=vertical, db=db, gate=gate
                )
                reports.append(report)
            except Exception as exc:
                logger.error(
                    "calibration_vertical_failed",
                    vertical=vertical,
                    error=str(exc),
                )

    if settings.whatsapp_founder_phone and reports:
        summary = _format_report(reports)
        try:
            await send_deal_alert(
                phone=settings.whatsapp_founder_phone,
                store_name="DistroAgent Analytics",
                reply_summary=summary,
            )
        except Exception as exc:
            logger.error("calibration_notify_failed", error=str(exc))

    return {"verticals_calibrated": len(reports), "reports": reports}


@celery_app.task(name="calibration.run_daily")
def run_daily_calibration_task() -> dict[str, Any]:
    """Calibrate scoring weights from last 30 days of outcome data.

    Scheduled once per day via Celery beat.
    """
    logger.info("calibration_task_started")
    result = asyncio.run(_run_calibration())
    logger.info(
        "calibration_task_complete",
        verticals_calibrated=result["verticals_calibrated"],
    )
    return result
