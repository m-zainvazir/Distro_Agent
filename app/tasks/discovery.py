import asyncio

from celery import Task

from app.celery_app import celery_app
from app.core.logging import logger
from app.workflows.phase1_workflow import phase1_graph


@celery_app.task(bind=True, name="discovery.run_phase1")
def run_phase1_discovery(
    self: Task,
    brand_url: str,
    vertical_tag: str,
    location: str,
    tenant_id: str,
) -> dict:
    """Run the full Phase 1 pipeline inside a Celery worker.

    Returns a JSON-serialisable dict; Pydantic models are flattened via
    model_dump() so Celery's JSON backend can store them in Redis.
    """
    self.update_state(state="PROGRESS", meta={"progress": 10, "step": "starting"})
    logger.info("celery_phase1_started", task_id=self.request.id, brand_url=brand_url)

    async def _invoke() -> dict:
        return await phase1_graph.ainvoke(
            {
                "brand_url": brand_url,
                "vertical_tag": vertical_tag,
                "target_location": location,
                "tenant_id": tenant_id,
                "brand_profile": None,
                "store_candidates": [],
                "scored_stores": [],
                "report_url": "",
                "errors": [],
            }
        )

    self.update_state(state="PROGRESS", meta={"progress": 50, "step": "pipeline_running"})
    result = asyncio.run(_invoke())

    scored = result.get("scored_stores", [])
    serialised = {
        "scored_stores": [s.model_dump() for s in scored],
        "report_url": result.get("report_url", ""),
        "errors": result.get("errors", []),
    }

    logger.info(
        "celery_phase1_complete",
        task_id=self.request.id,
        scored=len(scored),
        errors=len(serialised["errors"]),
    )
    return serialised
