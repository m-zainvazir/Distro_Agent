"""Sending domain endpoints (Spec 304 — Blueprint Layer 20)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.dependencies import get_current_tenant
from app.core.logging import logger
from app.models.campaign import Tenant
from app.models.sending_domain import SendingDomain
from app.services.domain_service import daily_send_limit, provision_sending_domain
from app.tools.domain_registrar import DomainRegistrarError

router = APIRouter(prefix="/domains", tags=["domains"])


class ProvisionRequest(BaseModel):
    brand_name: str


class DomainResponse(BaseModel):
    id: str
    domain: str
    is_active: bool
    warmup_day: int
    daily_limit: int
    send_count: int
    bounce_count: int
    paused: bool
    paused_reason: str | None
    provisioning_status: str
    dns_verified_at: datetime | None


def _to_response(row: SendingDomain) -> DomainResponse:
    return DomainResponse(
        id=str(row.id),
        domain=str(row.domain),
        is_active=bool(row.is_active),
        warmup_day=int(row.warmup_day),  # type: ignore[arg-type]
        daily_limit=daily_send_limit(row),
        send_count=int(row.send_count),  # type: ignore[arg-type]
        bounce_count=int(row.bounce_count),  # type: ignore[arg-type]
        paused=bool(row.paused),
        paused_reason=str(row.paused_reason) if row.paused_reason else None,
        provisioning_status=str(row.provisioning_status),
        dns_verified_at=row.dns_verified_at,  # type: ignore[arg-type]
    )


@router.get("", response_model=list[DomainResponse])
async def list_domains(
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DomainResponse]:
    """List all sending domains for the authenticated tenant."""
    result = await db.execute(
        select(SendingDomain).where(
            SendingDomain.tenant_id == uuid.UUID(str(tenant.id))
        )
    )
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


@router.post("/provision", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def provision_domain(
    body: ProvisionRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DomainResponse:
    """Provision a secondary sending domain with SPF/DKIM/DMARC via Cloudflare.

    Requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID to be set.
    The domain is registered under the brand name and placed into warmup-day-1.
    """
    tenant_id = uuid.UUID(str(tenant.id))
    try:
        domain_row = await provision_sending_domain(
            tenant_id=tenant_id,
            brand_name=body.brand_name,
            db=db,
        )
    except DomainRegistrarError as exc:
        logger.warning("domain_provision_failed", tenant_id=str(tenant_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error_code": "DOMAIN_PROVISION_FAILED", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_DOMAIN", "message": str(exc)},
        ) from exc

    return _to_response(domain_row)
