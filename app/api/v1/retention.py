"""Retention trigger endpoint — fired by an external cron, not a logged-in user.

`POST /api/v1/retention/run` scans closed deals across all tenants and runs the
Retention agent for each. It is protected by a shared `cron_token` (sent as the
`X-Cron-Token` header) rather than a tenant JWT, because the scheduler has no
tenant context. Disabled (503) until `CRON_TOKEN` is configured.

Point a daily Railway cron / cron-job.org / UptimeRobot at this URL.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger

router = APIRouter(prefix="/retention", tags=["retention"])


def _verify_cron_token(x_cron_token: str | None) -> None:
    if not settings.cron_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron trigger not configured (CRON_TOKEN unset).",
        )
    if not x_cron_token or not hmac.compare_digest(x_cron_token, settings.cron_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid cron token."
        )


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_retention(
    x_cron_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a retention sweep over closed deals. Cron-token protected."""
    _verify_cron_token(x_cron_token)

    from app.services.retention_trigger import run_retention_sweep

    summary = await run_retention_sweep(db)
    logger.info("retention_run_endpoint", **summary)
    return {"status": "ok", **summary}
