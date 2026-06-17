"""Tenant-level settings lookups used by agents at runtime."""
import uuid

from sqlalchemy import select

from app.agents.hitl_gate import ASSIST
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.models.campaign import Tenant


async def get_autonomy_mode(tenant_id: str) -> str:
    """Return the tenant's autonomy_mode, defaulting to ASSIST on any miss/error.

    Defaulting to ASSIST is the fail-safe: a lookup failure must never silently
    relax the HITL gate into autonomous sending.
    """
    if not tenant_id:
        return ASSIST
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Tenant.autonomy_mode).where(
                    Tenant.id == uuid.UUID(str(tenant_id))
                )
            )
            mode = result.scalar_one_or_none()
            return mode or ASSIST
    except Exception as exc:
        logger.warning(
            "autonomy_mode_lookup_failed", tenant_id=str(tenant_id), error=str(exc)
        )
        return ASSIST
