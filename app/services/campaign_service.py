"""Campaign service — tracks pending HITL approvals keyed by email_id.

Block C's copywriter_agent stores approval requests here when it hits the
interrupt node.  Block D's resume module reads from here to map an
email_id back to its LangGraph thread_id.
"""
from __future__ import annotations

from app.core.logging import logger

# In-memory store: email_id -> {"thread_id": str, "store_name": str}
_pending_approvals: dict[str, dict[str, str]] = {}


def register_pending_approval(
    email_id: str,
    thread_id: str,
    store_name: str,
    graph_type: str = "copywriter",
    tenant_id: str = "",
) -> None:
    """Called by the agent HITL nodes to register an interrupted run."""
    _pending_approvals[email_id] = {
        "thread_id": thread_id,
        "store_name": store_name,
        "graph_type": graph_type,
        "tenant_id": tenant_id,
    }
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
    return _pending_approvals.get(email_id)


def remove_pending_approval(email_id: str) -> None:
    """Remove a resolved approval from the pending store."""
    _pending_approvals.pop(email_id, None)
    logger.info("campaign_approval_removed", email_id=email_id)


# Alias used by the copywriter agent's hitl_approval_node.
register_pending = register_pending_approval
