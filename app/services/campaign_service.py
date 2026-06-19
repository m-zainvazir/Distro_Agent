"""Campaign service — tracks pending HITL approvals keyed by email_id.

Block C's copywriter_agent (and the negotiator / scheduling agents) store
approval requests here when they hit an interrupt node. Block D's resume module
reads from here to map an email_id back to its LangGraph thread_id.

Backed by Redis (via app.core.state_store) so pending approvals survive a
process restart and are visible across workers; falls back to an in-memory dict
when Redis is unavailable. Functions stay synchronous because they are called
from both async graph nodes and sync Celery tasks (app/tasks/reply_tasks.py).
"""
from __future__ import annotations

from app.core.logging import logger
from app.core.state_store import StateStore

# Pending approvals can wait on a human for a while — keep them for 7 days.
_PENDING_TTL_SECONDS = 7 * 24 * 3600

# email_id -> {"thread_id", "store_name", "graph_type", "tenant_id"}
_store = StateStore("campaign:approval", default_ttl=_PENDING_TTL_SECONDS)


def register_pending_approval(
    email_id: str,
    thread_id: str,
    store_name: str,
    graph_type: str = "copywriter",
    tenant_id: str = "",
) -> None:
    """Called by the agent HITL nodes to register an interrupted run."""
    _store.set(
        email_id,
        {
            "thread_id": thread_id,
            "store_name": store_name,
            "graph_type": graph_type,
            "tenant_id": tenant_id,
        },
    )
    logger.info(
        "campaign_approval_registered",
        email_id=email_id,
        thread_id=thread_id,
        store_name=store_name,
        graph_type=graph_type,
        tenant_id=tenant_id,
    )


def get_pending_approval(email_id: str) -> dict[str, str] | None:
    """Return the pending approval record for an email_id, or None if not found."""
    return _store.get(email_id)


def remove_pending_approval(email_id: str) -> None:
    """Remove a resolved approval from the pending store."""
    _store.delete(email_id)
    logger.info("campaign_approval_removed", email_id=email_id)


def list_pending_approval_ids() -> list[str]:
    """Return all email_ids currently awaiting approval."""
    return _store.keys()


# Alias used by the copywriter agent's hitl_approval_node.
register_pending = register_pending_approval
