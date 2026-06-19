"""In-process background scheduler for the retention sweep.

Runs inside the single live FastAPI/Railway service — no Celery, no external
cron required. Opt-in via ``settings.retention_sweep_interval_hours`` (0 = off).
The sweep is idempotent (pitched deals flip to ``restock_pitched``), so a restart
or overlap never double-pitches.
"""
from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import logger


async def _run_sweep_once() -> None:
    """Open a DB session and run one retention sweep, swallowing errors."""
    from app.core.database import AsyncSessionLocal
    from app.services.retention_trigger import run_retention_sweep

    try:
        async with AsyncSessionLocal() as db:
            summary = await run_retention_sweep(db)
        logger.info("retention_scheduler_swept", **summary)
    except Exception as exc:
        logger.error("retention_scheduler_failed", error=str(exc))


async def _retention_loop(interval_hours: int) -> None:
    """Sleep then sweep, forever. Waits one interval before the first run so a
    restart storm doesn't trigger an immediate sweep."""
    interval_seconds = interval_hours * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        await _run_sweep_once()


def start_retention_scheduler() -> asyncio.Task | None:
    """Start the retention loop if enabled; return its Task (or None if disabled)."""
    hours = settings.retention_sweep_interval_hours
    if hours <= 0:
        logger.info("retention_scheduler_disabled")
        return None
    logger.info("retention_scheduler_started", interval_hours=hours)
    return asyncio.create_task(_retention_loop(hours))
