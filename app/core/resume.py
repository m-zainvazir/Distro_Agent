"""Resume a paused LangGraph workflow by email_id.

Called by the WhatsApp webhook handler (or the campaigns approve/reject API)
after a founder taps Approve or Reject on the approval card.
"""
from __future__ import annotations

from langgraph.types import Command

from app.core.logging import logger
from app.services.campaign_service import get_pending_approval, remove_pending_approval


async def _resume_followup(email_id: str, approved: bool) -> None:
    """Handle approval/rejection of a follow-up email that has no graph thread.

    Approved  → send the follow-up via email_service
    Rejected  → mark the OutreachEmail as 'rejected' and stop outreach
    """
    import uuid as _uuid

    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail

    async with AsyncSessionLocal() as db:
        try:
            oid = _uuid.UUID(email_id)
        except ValueError:
            logger.error("resume_followup_bad_id", email_id=email_id)
            return

        email = await db.get(OutreachEmail, oid)
        if email is None:
            logger.warning("resume_followup_not_found", email_id=email_id)
            return

        if approved:
            from app.services.email_service import send_outreach_email

            try:
                await send_outreach_email(email, db)
                logger.info("followup_email_sent", email_id=email_id)
            except Exception as exc:
                logger.error("followup_send_failed", email_id=email_id, error=str(exc))
                raise
        else:
            email.outcome = "rejected"
            await db.commit()
            logger.info("followup_email_rejected", email_id=email_id)


async def resume_graph_for_email(email_id: str, approved: bool) -> None:
    """Resume the paused graph for *email_id*.

    Routes to the correct agent graph based on the graph_type stored in the
    pending approval record (negotiator | scheduling | copywriter).

    Args:
        email_id: Identifier that was embedded in the WhatsApp button payload.
        approved: True if the founder tapped Approve, False for Reject.
    """
    record = get_pending_approval(email_id)
    if record is None:
        logger.warning(
            "resume_no_pending_approval",
            email_id=email_id,
            approved=approved,
        )
        raise KeyError(f"No pending approval found for email_id={email_id!r}")

    thread_id: str = record["thread_id"]
    graph_type: str = record.get("graph_type", "copywriter")

    logger.info(
        "resume_graph_starting",
        email_id=email_id,
        thread_id=thread_id,
        graph_type=graph_type,
        approved=approved,
    )

    try:
        from app.core.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
    except Exception as exc:
        logger.warning("resume_checkpointer_fallback", error=str(exc))
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()

    if graph_type == "followup":
        await _resume_followup(email_id=email_id, approved=approved)
        remove_pending_approval(email_id)
        logger.info(
            "resume_followup_complete",
            email_id=email_id,
            approved=approved,
        )
        return

    if graph_type == "phase2":
        from app.workflows.phase2_workflow import build_phase2_graph

        graph = build_phase2_graph(checkpointer=checkpointer)
    elif graph_type == "negotiator":
        from app.agents.negotiator_agent import build_negotiator_graph

        graph = build_negotiator_graph(checkpointer=checkpointer)
    elif graph_type == "scheduling":
        from app.agents.scheduling_agent import build_scheduling_graph

        graph = build_scheduling_graph(checkpointer=checkpointer)
    elif graph_type == "retention":
        from app.agents.retention_agent import build_retention_graph

        graph = build_retention_graph(checkpointer=checkpointer)
    else:
        from app.agents.copywriter_agent import build_copywriter_graph

        graph = build_copywriter_graph(checkpointer=checkpointer)

    config: dict = {"configurable": {"thread_id": thread_id}}
    try:
        await graph.ainvoke(Command(resume=approved), config=config)
    except Exception as exc:
        logger.error(
            "resume_graph_failed",
            email_id=email_id,
            thread_id=thread_id,
            graph_type=graph_type,
            approved=approved,
            error=str(exc),
        )
        raise

    remove_pending_approval(email_id)
    logger.info(
        "resume_graph_complete",
        email_id=email_id,
        thread_id=thread_id,
        graph_type=graph_type,
        approved=approved,
    )
