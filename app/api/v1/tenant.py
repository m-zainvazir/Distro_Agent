"""Tenant settings endpoints — autonomy mode (Layer 8)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.hitl_gate import AUTONOMY_MODES
from app.core.database import get_db
from app.core.dependencies import get_current_tenant
from app.models.campaign import Tenant

router = APIRouter(prefix="/tenant", tags=["tenant"])


class AutonomyModeUpdate(BaseModel):
    autonomy_mode: str

    @field_validator("autonomy_mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in AUTONOMY_MODES:
            raise ValueError(f"autonomy_mode must be one of {list(AUTONOMY_MODES)}")
        return v


class TenantSettingsResponse(BaseModel):
    tenant_id: uuid.UUID
    autonomy_mode: str


@router.patch("/autonomy-mode", response_model=TenantSettingsResponse)
async def update_autonomy_mode(
    payload: AutonomyModeUpdate,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantSettingsResponse:
    """Set the authenticated tenant's autonomy mode (assist/semi_auto/full_auto)."""
    # SQLAlchemy Column[str] false positive (same class as resume.py / domain_service.py);
    # proper fix is the deferred Mapped[] model migration.
    tenant.autonomy_mode = payload.autonomy_mode  # type: ignore[assignment]
    db.add(tenant)
    await db.commit()
    return TenantSettingsResponse(
        tenant_id=uuid.UUID(str(tenant.id)), autonomy_mode=payload.autonomy_mode
    )
