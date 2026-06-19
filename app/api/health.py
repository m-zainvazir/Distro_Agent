"""Health endpoints.

`/health`    — liveness: never touches the DB, so Railway's health check stays
               green even when Neon's compute is suspended.
`/health/db` — readiness: pings the DB (with cold-start retries) and is the probe
               an uptime monitor should hit every few minutes to keep Neon awake.
"""
from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.database import check_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe — process is up. Does not depend on the database."""
    return {"status": "ok", "langsmith": bool(settings.langsmith_api_key)}


@router.get("/health/db")
async def health_db(response: Response) -> dict:
    """Readiness probe — verifies the database answers (waking Neon if suspended)."""
    result = await check_db()
    if not result["ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "db": "down", **result}
    return {"status": "ok", "db": "ok", **result}
