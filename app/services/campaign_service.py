"""Orchestrates outreach campaigns — one CopywriterAgent invocation per store."""

import uuid
from typing import Any

from app.agents.copywriter_agent import CopywriterState, build_copywriter_graph
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import ScoredStore

# Module-level in-memory store: email_id → {"thread_id": ..., "store_name": ...}
# Replace with Redis in production.
_pending_approvals: dict[str, dict[str, Any]] = {}


def get_pending_approval(email_id: str) -> dict[str, Any] | None:
    return _pending_approvals.get(email_id)


def register_pending(email_id: str, thread_id: str, store_name: str) -> None:
    _pending_approvals[email_id] = {"thread_id": thread_id, "store_name": store_name}


async def start_email_campaign(
    stores: list[ScoredStore],
    brand_profile: BrandProfile,
    founder_name: str,
    email_tone: str,
    tenant_id: str,
    checkpointer: Any = None,
) -> list[str]:
    """Invoke CopywriterAgent for each HIGH/MEDIUM store.

    Returns a list of thread_ids — one per store kicked off. Each thread_id
    can be used with Command(resume=...) to approve or reject the draft.
    """
    graph = build_copywriter_graph(checkpointer=checkpointer)
    thread_ids: list[str] = []

    for store in stores:
        if store.outreach_priority not in ("HIGH", "MEDIUM"):
            continue

        thread_id = str(uuid.uuid4())
        initial_state: CopywriterState = {
            "store": store,
            "brand_profile": brand_profile,
            "founder_name": founder_name,
            "email_tone": email_tone,
            "tenant_id": tenant_id,
            "campaign_id": "",
            "store_db_id": "",
            "draft_subject_a": "",
            "draft_subject_b": "",
            "draft_body": "",
            "personalization_score": 0.0,
            "critique_notes": "",
            "revision_count": 0,
            "approved": None,
            "final_email": None,
        }
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

        try:
            await graph.ainvoke(initial_state, config=config)
        except Exception as exc:
            # Graph pauses at interrupt — this is expected with a checkpointer.
            # Without a checkpointer it raises GraphInterrupt.
            logger.info(
                "campaign_graph_paused",
                thread_id=thread_id,
                store=store.store.name,
                reason=str(exc)[:80],
            )

        thread_ids.append(thread_id)
        logger.info("campaign_started", thread_id=thread_id, store=store.store.name)

    return thread_ids
