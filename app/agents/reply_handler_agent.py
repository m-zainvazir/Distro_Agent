"""ReplyHandlerAgent — classifies inbound buyer replies and routes by intent.

Intent taxonomy
---------------
INTERESTED      buyer wants more info / partnership → send catalog or route to Scheduling
OBJECTION       price / MOQ / shipping / terms concern → route to Negotiator (Block G)
NOT_INTERESTED  explicit rejection → mark lead lost, stop outreach
MEETING_REQUEST buyer asks for a call → route to Scheduling (Block H)
NO_REPLY        time-based; handled by the follow-up sequencer, not this classifier
"""
from __future__ import annotations

import re
import uuid
from typing import Literal

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from app.core.logging import logger

# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTERESTED = "INTERESTED"
OBJECTION = "OBJECTION"
NOT_INTERESTED = "NOT_INTERESTED"
MEETING_REQUEST = "MEETING_REQUEST"

Intent = Literal["INTERESTED", "OBJECTION", "NOT_INTERESTED", "MEETING_REQUEST"]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class ReplyHandlerState(TypedDict):
    reply_text: str
    sender_email: str
    gmail_thread_id: str
    email_id: str
    tenant_id: str
    intent: str
    routing_action: str
    notes: str


# ---------------------------------------------------------------------------
# Classifier — keyword scoring, no external API calls, fully testable
# ---------------------------------------------------------------------------

_MEETING_PHRASES = [
    "schedule a call",
    "set up a meeting",
    "book a time",
    "hop on a call",
    "have a chat",
    "zoom call",
    "phone call",
    "get on a call",
    "schedule time",
    "calendar link",
    "arrange a meeting",
]
_MEETING_WORDS = ["meeting", "calendar", "schedule", "zoom", "phone"]

_NOT_INTERESTED_PHRASES = [
    "not interested",
    "no thank",
    "not looking",
    "don't need",
    "do not need",
    "not a good fit",
    "not the right fit",
    "unsubscribe",
    "remove me",
    "please remove",
    "stop emailing",
    "opt out",
]

_OBJECTION_WORDS = [
    "price",
    "expensive",
    "costly",
    "moq",
    "minimum order",
    "minimum quantity",
    "shipping cost",
    "shipping fee",
    "terms",
    "budget",
    "afford",
    "too high",
    "too much",
    "concerned about",
    "worry about",
]

_INTERESTED_PHRASES = [
    "tell me more",
    "sounds great",
    "sounds good",
    "love to",
    "would love",
    "interested",
    "would like",
    "can you send",
    "send me",
    "more information",
    "sign me up",
    "how do we",
    "great idea",
    "looks great",
    "keen to",
    "happy to",
    "yes please",
    "absolutely",
]


def classify_intent(text: str) -> Intent:
    """Classify buyer reply text into one of four intents.

    Uses keyword scoring — no external API calls.  Multi-word phrase matches
    score 2 points; single-word matches score 1.  Ties and zero-score texts
    default to INTERESTED (any reply is a positive signal; NO_REPLY is handled
    by the sequencer separately).
    """
    lower = text.lower()
    scores: dict[str, int] = {
        INTERESTED: 0,
        OBJECTION: 0,
        NOT_INTERESTED: 0,
        MEETING_REQUEST: 0,
    }

    for phrase in _MEETING_PHRASES:
        if phrase in lower:
            scores[MEETING_REQUEST] += 2

    for word in _MEETING_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            scores[MEETING_REQUEST] += 1

    for phrase in _NOT_INTERESTED_PHRASES:
        if phrase in lower:
            scores[NOT_INTERESTED] += 2

    for word in _OBJECTION_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            scores[OBJECTION] += 1

    for phrase in _INTERESTED_PHRASES:
        if phrase in lower:
            scores[INTERESTED] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return INTERESTED  # any reply without a strong signal is soft interest
    return best  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def classify_node(state: ReplyHandlerState) -> dict:
    intent = classify_intent(state["reply_text"])
    logger.info("reply_classified", email_id=state.get("email_id", ""), intent=intent)
    return {"intent": intent}


async def handle_interested_node(state: ReplyHandlerState) -> dict:
    logger.info("reply_interested", email_id=state.get("email_id", ""))
    return {
        "routing_action": "send_catalog",
        "notes": "Buyer expressed interest — send catalog and schedule follow-up.",
    }


async def handle_objection_node(state: ReplyHandlerState) -> dict:
    """Invoke Negotiator Agent (Block G) with a default WholesaleRulebook."""
    from app.agents.negotiator_agent import NegotiatorState, build_negotiator_graph
    from app.core.checkpointer import get_checkpointer
    from app.models.rulebook import WholesaleRulebook

    logger.info("reply_objection", email_id=state.get("email_id", ""))

    thread_id = f"negotiator-{state.get('email_id') or uuid.uuid4()}"
    checkpointer = await get_checkpointer()
    negotiator = build_negotiator_graph(checkpointer=checkpointer)

    initial: NegotiatorState = {
        "objection_text": state["reply_text"],
        "buyer_email": state["sender_email"],
        "original_email_id": state.get("email_id", ""),
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
        "graph_thread_id": thread_id,
    }

    try:
        result = await negotiator.ainvoke(
            initial,
            config={"configurable": {"thread_id": thread_id}},
        )
        notes = (
            f"Negotiator started (thread_id={thread_id}); "
            f"sub_action={result.get('routing_action', 'pending')}; "
            f"final={'yes' if result.get('final_counter') else 'pending'}"
        )
    except Exception as exc:
        logger.error("negotiator_invocation_failed", error=str(exc))
        notes = f"Negotiator failed to start: {exc}"

    return {"routing_action": "route_to_negotiator", "notes": notes}


async def handle_not_interested_node(state: ReplyHandlerState) -> dict:
    logger.info("reply_not_interested", email_id=state.get("email_id", ""))
    return {
        "routing_action": "mark_lead_lost",
        "notes": "Buyer is not interested — marking lead lost, stopping outreach.",
    }


async def handle_meeting_request_node(state: ReplyHandlerState) -> dict:
    """Invoke Scheduling Agent (Block H). explicit_request=True bypasses the lead-score guardrail."""
    from app.agents.scheduling_agent import SchedulingState, build_scheduling_graph
    from app.core.checkpointer import get_checkpointer

    logger.info("reply_meeting_request", email_id=state.get("email_id", ""))

    thread_id = f"scheduling-{state.get('email_id') or uuid.uuid4()}"
    checkpointer = await get_checkpointer()
    scheduler = build_scheduling_graph(checkpointer=checkpointer)

    initial: SchedulingState = {
        "lead_score": 0.0,
        "explicit_request": True,  # buyer asked for a meeting → guardrail always passes
        "buyer_email": state["sender_email"],
        "buyer_name": "",
        "store_name": "",
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

    try:
        result = await scheduler.ainvoke(
            initial,
            config={"configurable": {"thread_id": thread_id}},
        )
        notes = (
            f"Scheduling agent started (thread_id={thread_id}); "
            f"sub_action={result.get('routing_action', 'pending')}"
        )
    except Exception as exc:
        logger.error("scheduling_invocation_failed", error=str(exc))
        notes = f"Scheduling agent failed to start: {exc}"

    return {"routing_action": "route_to_scheduling", "notes": notes}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_by_intent(
    state: ReplyHandlerState,
) -> Literal["interested", "objection", "not_interested", "meeting_request"]:
    mapping = {
        INTERESTED: "interested",
        OBJECTION: "objection",
        NOT_INTERESTED: "not_interested",
        MEETING_REQUEST: "meeting_request",
    }
    return mapping.get(state["intent"], "interested")  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_reply_handler_graph():
    """Compile the ReplyHandler graph (no checkpointer needed — no interrupts)."""
    graph = StateGraph(ReplyHandlerState)

    graph.add_node("classify", classify_node)
    graph.add_node("interested", handle_interested_node)
    graph.add_node("objection", handle_objection_node)
    graph.add_node("not_interested", handle_not_interested_node)
    graph.add_node("meeting_request", handle_meeting_request_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        route_by_intent,
        {
            "interested": "interested",
            "objection": "objection",
            "not_interested": "not_interested",
            "meeting_request": "meeting_request",
        },
    )

    graph.add_edge("interested", END)
    graph.add_edge("objection", END)
    graph.add_edge("not_interested", END)
    graph.add_edge("meeting_request", END)

    return graph.compile()
