"""KPI metrics endpoint — JWT-protected, tenant-scoped."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_tenant
from app.models.campaign import Tenant
from app.schemas.metrics import KpiSummary
from app.services.metrics_service import compute_tenant_kpis

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/kpis", response_model=KpiSummary)
async def get_kpis(
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    lookback_days: int = Query(default=30, ge=1, le=365),
) -> KpiSummary:
    """Return KPI summary for the authenticated tenant only."""
    try:
        return await compute_tenant_kpis(
            tenant_id=uuid.UUID(str(tenant.id)),
            lookback_days=lookback_days,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
