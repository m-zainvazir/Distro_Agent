from pathlib import Path
from typing import Annotated

import markdown as md
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.celery_app import celery_app
from app.core.dependencies import get_current_tenant
from app.models.campaign import Tenant
from app.models.store_candidate import ScoredStore
from app.tasks.discovery import run_phase1_discovery

router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryStartRequest(BaseModel):
    brand_url: str
    vertical_tag: str
    location: str


class DiscoveryStartResponse(BaseModel):
    task_id: str
    status: str = "processing"


class DiscoveryStatusResponse(BaseModel):
    status: str
    progress: int


class DiscoveryReportResponse(BaseModel):
    stores: list[ScoredStore]
    report_html: str
    errors: list[str] = []


def _celery_state_to_status(state: str) -> tuple[str, int]:
    mapping = {
        "PENDING": ("processing", 0),
        "RECEIVED": ("processing", 5),
        "STARTED": ("processing", 10),
        "PROGRESS": ("processing", 50),
        "SUCCESS": ("complete", 100),
        "FAILURE": ("error", 0),
        "REVOKED": ("error", 0),
        "RETRY": ("processing", 10),
    }
    return mapping.get(state, ("processing", 0))


def _build_report_html(report_url: str) -> str:
    if not report_url:
        return "<p>Report not available.</p>"
    path = Path(report_url)
    if not path.exists():
        return "<p>Report not available.</p>"
    return md.markdown(path.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])


@router.post("/start", response_model=DiscoveryStartResponse, status_code=202)
async def start_discovery(
    body: DiscoveryStartRequest,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> DiscoveryStartResponse:
    task = run_phase1_discovery.delay(
        brand_url=body.brand_url,
        vertical_tag=body.vertical_tag,
        location=body.location,
        tenant_id=str(tenant.id),
    )
    return DiscoveryStartResponse(task_id=task.id)


@router.get("/{task_id}/status", response_model=DiscoveryStatusResponse)
async def get_discovery_status(
    task_id: str,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> DiscoveryStatusResponse:
    result = AsyncResult(task_id, app=celery_app)
    status, progress = _celery_state_to_status(result.state)
    if result.state == "PROGRESS" and isinstance(result.info, dict):
        progress = result.info.get("progress", 50)
    return DiscoveryStatusResponse(status=status, progress=progress)


@router.get("/{task_id}/report", response_model=DiscoveryReportResponse)
async def get_discovery_report(
    task_id: str,
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> DiscoveryReportResponse:
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "FAILURE":
        raise HTTPException(status_code=500, detail="Discovery task failed.")
    if result.state != "SUCCESS":
        raise HTTPException(
            status_code=409,
            detail=f"Task not complete yet (state={result.state}). Poll /status first.",
        )
    payload: dict = result.result
    stores = [ScoredStore(**s) for s in payload.get("scored_stores", [])]
    return DiscoveryReportResponse(
        stores=stores,
        report_html=_build_report_html(payload.get("report_url", "")),
        errors=payload.get("errors", []),
    )
