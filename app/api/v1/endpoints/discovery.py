from pathlib import Path
from typing import Any
import uuid

import markdown as md
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.core.logging import logger
from app.models.store_candidate import ScoredStore
from app.workflows.phase1_workflow import phase1_graph

router = APIRouter(prefix="/discovery", tags=["discovery"])

_PUBLIC_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# In-memory task store — sufficient for demo; lost on pod restart
_tasks: dict[str, dict[str, Any]] = {}


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


def _build_report_html(report_url: str) -> str:
    if not report_url:
        return "<p>Report not available.</p>"
    path = Path(report_url)
    if not path.exists():
        return "<p>Report not available.</p>"
    return md.markdown(path.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])


async def _run_discovery(
    task_id: str,
    brand_url: str,
    vertical_tag: str,
    location: str,
) -> None:
    try:
        _tasks[task_id] = {"status": "processing", "progress": 30}
        result = await phase1_graph.ainvoke(
            {
                "brand_url": brand_url,
                "vertical_tag": vertical_tag,
                "target_location": location,
                "tenant_id": _PUBLIC_TENANT_ID,
                "brand_profile": None,
                "store_candidates": [],
                "scored_stores": [],
                "report_url": "",
                "errors": [],
            }
        )
        scored = result.get("scored_stores", [])
        _tasks[task_id] = {
            "status": "complete",
            "progress": 100,
            "result": {
                "scored_stores": [s.model_dump() for s in scored],
                "report_url": result.get("report_url", ""),
                "errors": result.get("errors", []),
            },
        }
        logger.info("discovery_complete", task_id=task_id, scored=len(scored))
    except Exception as exc:
        logger.exception("discovery_failed", task_id=task_id, error=str(exc))
        _tasks[task_id] = {"status": "error", "progress": 0}


@router.post("/start", response_model=DiscoveryStartResponse, status_code=202)
async def start_discovery(
    body: DiscoveryStartRequest,
    background_tasks: BackgroundTasks,
) -> DiscoveryStartResponse:
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {"status": "processing", "progress": 0}
    background_tasks.add_task(
        _run_discovery,
        task_id,
        body.brand_url,
        body.vertical_tag,
        body.location,
    )
    return DiscoveryStartResponse(task_id=task_id)


@router.get("/{task_id}/status", response_model=DiscoveryStatusResponse)
async def get_discovery_status(task_id: str) -> DiscoveryStatusResponse:
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return DiscoveryStatusResponse(status=task["status"], progress=task["progress"])


@router.get("/{task_id}/report", response_model=DiscoveryReportResponse)
async def get_discovery_report(task_id: str) -> DiscoveryReportResponse:
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] == "error":
        raise HTTPException(status_code=500, detail="Discovery task failed.")
    if task["status"] != "complete":
        raise HTTPException(
            status_code=409,
            detail=f"Task not complete yet (status={task['status']}). Poll /status first.",
        )
    payload = task["result"]
    stores = [ScoredStore(**s) for s in payload.get("scored_stores", [])]
    return DiscoveryReportResponse(
        stores=stores,
        report_html=_build_report_html(payload.get("report_url", "")),
        errors=payload.get("errors", []),
    )
