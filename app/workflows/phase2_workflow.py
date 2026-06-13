"""Phase 2 outreach campaign orchestration.

Chains Blocks C–I (Copywriter → Email → Reply → Negotiate / Schedule) into a
single LangGraph StateGraph with well-defined HITL interrupt points.

Sub-agents (Copywriter, Negotiator, Scheduler) run under namespaced thread_ids.
Any HITL interrupt() inside a sub-graph is forwarded up through the master
interrupt() so the operator sees one unified approval stream.
"""
from __future__ import annotations

import uuid
from typing import Literal

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.reply_handler_agent import classify_intent
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.outreach import OutreachEmailDraft
from app.models.store_candidate import ScoredStore

# ---------------------------------------------------------------------------
# Phase constants
# ---------------------------------------------------------------------------

PHASE_DRAFTING = "drafting"
PHASE_EMAIL_SENT = "email_sent"
PHASE_AWAITING_REPLY = "awaiting_reply"
PHASE_WON = "won"
PHASE_LOST = "lost"
PHASE_DORMANT = "dormant"
PHASE_NEGOTIATING = "negotiating"
PHASE_SCHEDULING = "scheduling"
PHASE_DRAFT_REJECTED = "draft_rejected"
PHASE_DISPATCH_FAILED = "dispatch_failed"

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class Phase2State(TypedDict):
    # ── Inputs ───────────────────────────────────────────────────────────────
    tenant_id: str
    brand_profile: BrandProfile
    store: ScoredStore
    founder_name: str
    email_tone: str         # "warm" | "professional" | "casual"
    campaign_id: str        # OutreachCampaign DB id (empty → skip DB persist)
    store_db_id: str        # StoreCandidate DB id   (empty → skip DB persist)
    buyer_email: str        # recipient address
    buyer_name: str         # buyer's name for personalisation

    # ── Copywriter ───────────────────────────────────────────────────────────
    approved_email: OutreachEmailDraft | None
    copywriter_thread_id: str

    # ── Email dispatch ────────────────────────────────────────────────────────
    outreach_email_id: str
    email_sent: bool

    # ── Reply ────────────────────────────────────────────────────────────────
    reply_text: str
    sender_email: str
    gmail_thread_id: str
    reply_intent: str       # INTERESTED | OBJECTION | NOT_INTERESTED | MEETING_REQUEST

    # ── Sub-agent thread IDs ─────────────────────────────────────────────────
    negotiation_thread_id: str
    scheduling_thread_id: str

    # ── Scheduling output ────────────────────────────────────────────────────
    meet_link: str

    # ── Lifecycle ────────────────────────────────────────────────────────────
    phase: str
    follow_up_count: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Email dispatch helper — module-level so tests can patch it
# ---------------------------------------------------------------------------


async def _dispatch_draft(
    approved: OutreachEmailDraft,
    buyer_email: str,
    campaign_id: str,
    store_db_id: str,
    tenant_id: str = "",
) -> str:
    """Create OutreachEmail record, send via SendGrid, return email_id."""
    from app.core.database import AsyncSessionLocal
    from app.models.campaign import OutreachEmail as OutreachEmailRecord
    from app.services.email_service import send_outreach_email

    async with AsyncSessionLocal() as db:
        record = OutreachEmailRecord(
            campaign_id=campaign_id or None,
            store_id=store_db_id or None,
            tenant_id=tenant_id or None,
            subject=approved.subject_a,
            body=approved.body,
            to_email=buyer_email,
            outcome="approved",
        )
        db.add(record)
        await db.flush()
        await send_outreach_email(record, db)
        return str(record.id)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def invoke_copywriter_node(state: Phase2State) -> dict:
    """Run CopywriterAgent sub-graph; forward HITL interrupts to the caller."""
    from app.agents.copywriter_agent import CopywriterState, build_copywriter_graph
    from app.core.checkpointer import get_checkpointer
    from langgraph.types import Command

    thread_id = (
        state.get("copywriter_thread_id")
        or f"cw-{state.get('campaign_id') or uuid.uuid4()}"
    )
    checkpointer = await get_checkpointer()
    graph = build_copywriter_graph(checkpointer=checkpointer)
    config: dict = {"configurable": {"thread_id": thread_id}}

    cw_input: CopywriterState = {
        "store": state["store"],
        "brand_profile": state["brand_profile"],
        "founder_name": state["founder_name"],
        "email_tone": state["email_tone"],
        "tenant_id": state["tenant_id"],
        "campaign_id": state["campaign_id"],
        "store_db_id": state["store_db_id"],
        "draft_subject_a": "",
        "draft_subject_b": "",
        "draft_body": "",
        "personalization_score": 0.0,
        "critique_notes": "",
        "revision_count": 0,
        "approved": None,
        "final_email": None,
        "token_usage": {"input": 0, "output": 0},
        "cost_usd": 0.0,
    }

    result = await graph.ainvoke(cw_input, config=config)

    # Forward every sub-graph HITL interrupt up to the master workflow caller
    while "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        approved = interrupt(
            {"type": "copywriter_hitl", "copywriter_thread_id": thread_id, **payload}
        )
        result = await graph.ainvoke(Command(resume=approved), config=config)

    final_email: OutreachEmailDraft | None = result.get("final_email")
    errors = list(state.get("errors", []))
    if not final_email:
        errors.append("copywriter: email rejected or no draft produced")

    logger.info(
        "phase2_copywriter_complete",
        thread_id=thread_id,
        approved=bool(final_email),
    )
    return {
        "approved_email": final_email,
        "copywriter_thread_id": thread_id,
        "phase": PHASE_DRAFTING,
        "errors": errors,
    }


def route_after_copywriter(state: Phase2State) -> str:
    return "dispatch_email" if state.get("approved_email") else "draft_rejected"


async def draft_rejected_node(state: Phase2State) -> dict:
    logger.info("phase2_draft_rejected", campaign_id=state.get("campaign_id", ""))
    return {"phase": PHASE_DRAFT_REJECTED}


async def dispatch_email_node(state: Phase2State) -> dict:
    """Create an OutreachEmail record, assert status=approved, send via SendGrid."""
    approved = state.get("approved_email")
    errors = list(state.get("errors", []))

    if not approved:
        errors.append("dispatch: no approved email in state")
        return {"email_sent": False, "phase": PHASE_DISPATCH_FAILED, "errors": errors}

    try:
        email_id = await _dispatch_draft(
            approved=approved,
            buyer_email=state["buyer_email"],
            campaign_id=state["campaign_id"],
            store_db_id=state["store_db_id"],
            tenant_id=state["tenant_id"],
        )
        logger.info(
            "phase2_email_dispatched",
            campaign_id=state.get("campaign_id", ""),
            email_id=email_id,
        )
        return {
            "email_sent": True,
            "outreach_email_id": email_id,
            "phase": PHASE_EMAIL_SENT,
            "errors": errors,
        }
    except Exception as exc:
        errors.append(f"dispatch: {exc}")
        logger.error("phase2_dispatch_failed", error=str(exc))
        return {"email_sent": False, "phase": PHASE_DISPATCH_FAILED, "errors": errors}


async def await_reply_node(state: Phase2State) -> dict:
    """Pause until a buyer reply arrives (resumed by Gmail poller or operator)."""
    reply_data: dict = interrupt(
        {
            "type": "await_reply",
            "campaign_id": state.get("campaign_id", ""),
            "store_name": state["store"].store.name,
            "outreach_email_id": state.get("outreach_email_id", ""),
        }
    )
    return {
        "reply_text": reply_data.get("reply_text", ""),
        "sender_email": reply_data.get("sender_email", ""),
        "gmail_thread_id": reply_data.get("gmail_thread_id", ""),
        "phase": PHASE_AWAITING_REPLY,
    }


async def classify_reply_node(state: Phase2State) -> dict:
    """Classify the buyer reply into an intent label."""
    reply_text = state.get("reply_text", "")
    if not reply_text:
        logger.info("phase2_no_reply_received", campaign_id=state.get("campaign_id", ""))
        return {"reply_intent": ""}

    intent = classify_intent(reply_text)
    logger.info(
        "phase2_reply_classified",
        campaign_id=state.get("campaign_id", ""),
        intent=intent,
    )
    return {"reply_intent": intent}


def route_by_intent(
    state: Phase2State,
) -> Literal[
    "handle_interested",
    "invoke_negotiator",
    "mark_lost",
    "invoke_scheduler",
    "handle_no_reply",
]:
    if not state.get("reply_text"):
        return "handle_no_reply"
    mapping: dict[str, str] = {
        "INTERESTED": "handle_interested",
        "OBJECTION": "invoke_negotiator",
        "NOT_INTERESTED": "mark_lost",
        "MEETING_REQUEST": "invoke_scheduler",
    }
    return mapping.get(state.get("reply_intent", ""), "handle_interested")  # type: ignore[return-value]


async def handle_interested_node(state: Phase2State) -> dict:
    logger.info(
        "phase2_buyer_interested",
        campaign_id=state.get("campaign_id", ""),
        store=state["store"].store.name,
    )
    return {"phase": PHASE_WON}


async def invoke_negotiator_node(state: Phase2State) -> dict:
    """Run NegotiatorAgent sub-graph; forward HITL interrupts."""
    from app.agents.negotiator_agent import NegotiatorState, build_negotiator_graph
    from app.core.checkpointer import get_checkpointer
    from app.models.rulebook import WholesaleRulebook
    from langgraph.types import Command

    thread_id = f"neg-{state.get('campaign_id') or uuid.uuid4()}-{uuid.uuid4().hex[:6]}"
    checkpointer = await get_checkpointer()
    graph = build_negotiator_graph(checkpointer=checkpointer)
    config: dict = {"configurable": {"thread_id": thread_id}}

    initial: NegotiatorState = {
        "objection_text": state["reply_text"],
        "buyer_email": state.get("sender_email") or state["buyer_email"],
        "buyer_name": state.get("sender_email") or state["buyer_email"],
        "original_email_id": state.get("outreach_email_id", ""),
        "tenant_id": state["tenant_id"],
        "rulebook": WholesaleRulebook(),
        "objection_type": "",
        "within_rulebook": False,
        "escalation_reason": "",
        "counter_offer_body": "",
        "counter_id": "",
        "revision_count": 0,
        "approved": None,
        "final_counter": None,
        "routing_action": "",
        "token_usage": {"input": 0, "output": 0},
        "cost_usd": 0.0,
        "graph_thread_id": thread_id,
        "invoice_line_items": [],
        "invoice_due_days": 30,
    }

    result = await graph.ainvoke(initial, config=config)

    while "__interrupt__" in result:
        approved = interrupt(
            {
                "type": "negotiator_hitl",
                "negotiation_thread_id": thread_id,
                **result["__interrupt__"][0].value,
            }
        )
        result = await graph.ainvoke(Command(resume=approved), config=config)

    logger.info(
        "phase2_negotiation_complete",
        thread_id=thread_id,
        sub_action=result.get("routing_action", ""),
    )
    return {"negotiation_thread_id": thread_id, "phase": PHASE_NEGOTIATING}


async def invoke_scheduler_node(state: Phase2State) -> dict:
    """Run SchedulingAgent sub-graph; forward HITL interrupts."""
    from app.agents.scheduling_agent import SchedulingState, build_scheduling_graph
    from app.core.checkpointer import get_checkpointer
    from langgraph.types import Command

    thread_id = f"sched-{state.get('campaign_id') or uuid.uuid4()}-{uuid.uuid4().hex[:6]}"
    checkpointer = await get_checkpointer()
    graph = build_scheduling_graph(checkpointer=checkpointer)
    config: dict = {"configurable": {"thread_id": thread_id}}

    initial: SchedulingState = {
        "lead_score": state["store"].final_score,
        "explicit_request": state.get("reply_intent") == "MEETING_REQUEST",
        "buyer_email": state.get("sender_email") or state["buyer_email"],
        "buyer_name": state["buyer_name"],
        "store_name": state["store"].store.name,
        "tenant_id": state["tenant_id"],
        "available_slots": [],
        "selected_slot": None,
        "proposal_body": "",
        "approved": None,
        "event_id": "",
        "meet_link": "",
        "routing_action": "",
        "graph_thread_id": thread_id,
    }

    result = await graph.ainvoke(initial, config=config)

    while "__interrupt__" in result:
        approved = interrupt(
            {
                "type": "scheduler_hitl",
                "scheduling_thread_id": thread_id,
                **result["__interrupt__"][0].value,
            }
        )
        result = await graph.ainvoke(Command(resume=approved), config=config)

    meet_link = result.get("meet_link", "")
    logger.info(
        "phase2_scheduling_complete", thread_id=thread_id, meet_link=meet_link
    )
    return {
        "scheduling_thread_id": thread_id,
        "meet_link": meet_link,
        "phase": PHASE_SCHEDULING,
    }


async def mark_lost_node(state: Phase2State) -> dict:
    logger.info(
        "phase2_lead_lost",
        campaign_id=state.get("campaign_id", ""),
        store=state["store"].store.name,
    )
    return {"phase": PHASE_LOST}


async def handle_no_reply_node(state: Phase2State) -> dict:
    """Mark the lead dormant; Celery tasks in reply_tasks.py handle timed follow-ups."""
    follow_up_count = state.get("follow_up_count", 0)
    logger.info(
        "phase2_no_reply",
        campaign_id=state.get("campaign_id", ""),
        follow_up_count=follow_up_count,
    )
    return {"phase": PHASE_DORMANT, "follow_up_count": follow_up_count}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_phase2_graph(checkpointer=None):
    """Compile the Phase 2 outreach orchestration graph.

    A checkpointer is required for the HITL interrupt() calls in
    await_reply_node and the sub-agent nodes.
    """
    graph = StateGraph(Phase2State)

    graph.add_node("invoke_copywriter", invoke_copywriter_node)
    graph.add_node("draft_rejected", draft_rejected_node)
    graph.add_node("dispatch_email", dispatch_email_node)
    graph.add_node("await_reply", await_reply_node)
    graph.add_node("classify_reply", classify_reply_node)
    graph.add_node("handle_interested", handle_interested_node)
    graph.add_node("invoke_negotiator", invoke_negotiator_node)
    graph.add_node("invoke_scheduler", invoke_scheduler_node)
    graph.add_node("mark_lost", mark_lost_node)
    graph.add_node("handle_no_reply", handle_no_reply_node)

    graph.set_entry_point("invoke_copywriter")

    graph.add_conditional_edges(
        "invoke_copywriter",
        route_after_copywriter,
        {"dispatch_email": "dispatch_email", "draft_rejected": "draft_rejected"},
    )
    graph.add_edge("draft_rejected", END)
    graph.add_edge("dispatch_email", "await_reply")
    graph.add_edge("await_reply", "classify_reply")
    graph.add_conditional_edges(
        "classify_reply",
        route_by_intent,
        {
            "handle_interested": "handle_interested",
            "invoke_negotiator": "invoke_negotiator",
            "mark_lost": "mark_lost",
            "invoke_scheduler": "invoke_scheduler",
            "handle_no_reply": "handle_no_reply",
        },
    )
    graph.add_edge("handle_interested", END)
    graph.add_edge("invoke_negotiator", END)
    graph.add_edge("invoke_scheduler", END)
    graph.add_edge("mark_lost", END)
    graph.add_edge("handle_no_reply", END)

    return graph.compile(checkpointer=checkpointer)
