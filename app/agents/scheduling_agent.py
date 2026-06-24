"""SchedulingAgent — proposes calendar slots and books meetings with qualified buyers.

Flow
----
guardrail → route_after_guardrail
    ├── END  (lead_score ≤ 8.0 AND no explicit call request)
    └── fetch_availability → propose_slots [HITL] → route_after_proposal
            ├── END  (founder rejected the proposal)
            └── wait_for_selection [interrupt: buyer picks slot]
                    → book → confirm → notify → END

Guardrail rule (CRITICAL)
--------------------------
Only proceed when  lead_score > 8.0  OR  explicit_request == True.
This protects the founder's calendar from low-value prospects.
"""
from __future__ import annotations

from datetime import datetime

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.hitl_gate import DEAL, request_human_approval
from app.core.config import settings
from app.core.logging import logger
from app.services.calendar_service import create_event, get_free_slots

_LEAD_SCORE_THRESHOLD = 8.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class SchedulingState(TypedDict):
    lead_score: float
    explicit_request: bool       # buyer explicitly asked for a call
    buyer_email: str
    buyer_name: str
    store_name: str
    tenant_id: str
    available_slots: list[dict]  # [{"start": ISO str, "end": ISO str}]
    selected_slot: dict | None   # set by wait_for_selection (buyer's choice)
    proposal_body: str
    approved: bool | None        # HITL result for proposal
    event_id: str
    meet_link: str
    routing_action: str
    graph_thread_id: str         # LangGraph thread_id for HITL resume routing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_slot(slot: dict) -> str:
    dt = datetime.fromisoformat(slot["start"])
    return dt.strftime("%A, %B %d at %I:%M %p UTC")


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def guardrail_node(state: SchedulingState) -> dict:
    """Block low-value prospects from reaching the calendar."""
    qualifies = state["lead_score"] > _LEAD_SCORE_THRESHOLD or state["explicit_request"]

    if not qualifies:
        logger.info(
            "scheduling_guardrail_blocked",
            lead_score=state["lead_score"],
            explicit_request=state["explicit_request"],
        )
        return {"routing_action": "blocked_by_guardrail"}

    logger.info(
        "scheduling_guardrail_passed",
        lead_score=state["lead_score"],
        explicit_request=state["explicit_request"],
    )
    return {"routing_action": ""}


def route_after_guardrail(state: SchedulingState) -> str:
    if state["routing_action"] == "blocked_by_guardrail":
        return "end"
    return "fetch_availability"


async def fetch_availability_node(state: SchedulingState) -> dict:
    """Fetch the founder's free 30-minute slots for the next 7 days."""
    try:
        slots = await get_free_slots(days_ahead=7, slot_duration_mins=30, max_slots=10)
    except Exception as exc:
        logger.error("fetch_availability_failed", error=str(exc))
        slots = []
    logger.info("scheduling_slots_fetched", count=len(slots))
    return {"available_slots": slots}


async def propose_slots_node(state: SchedulingState) -> dict:
    """Draft a 3-slot proposal email and pause for founder HITL approval."""
    slots = state["available_slots"][:3]

    lines = [
        f"Hi {state['buyer_name']},",
        "",
        f"It was great hearing from you about {state['store_name']}! "
        "I'd love to connect for a quick 30-minute call to explore a wholesale partnership.",
        "",
        "Here are three times that work well for me:",
        "",
    ]
    for i, slot in enumerate(slots, 1):
        lines.append(f"  Option {i}: {_fmt_slot(slot)}")
    lines += [
        "",
        "Just reply with your preferred option and I'll send a calendar invite "
        "with a Google Meet link right away.",
        "",
        "Looking forward to connecting!",
    ]
    proposal_body = "\n".join(lines)

    logger.info(
        "scheduling_hitl_requested",
        store_name=state["store_name"],
        slot_count=len(slots),
    )

    try:
        from app.services.campaign_service import register_pending
        from app.services.whatsapp_service import send_approval_card

        proposal_id = f"proposal-{state['store_name']}"
        register_pending(
            proposal_id,
            state.get("graph_thread_id", "unknown"),
            state["store_name"],
            graph_type="scheduling",
            tenant_id=state.get("tenant_id", ""),
        )
        await send_approval_card(
            phone=settings.whatsapp_founder_phone,
            email_preview=proposal_body[:300],
            email_id=proposal_id,
            store_name=state["store_name"],
        )
    except Exception as exc:
        logger.warning("scheduling_whatsapp_failed", error=str(exc))

    from app.services.tenant_service import get_autonomy_mode

    autonomy_mode = await get_autonomy_mode(state.get("tenant_id", ""))
    approved: bool = request_human_approval(
        {
            "type": "slot_proposal",
            "store_name": state["store_name"],
            "buyer_email": state["buyer_email"],
            "proposal_preview": proposal_body[:400],
            "slots": [_fmt_slot(s) for s in slots],
        },
        action_class=DEAL,
        autonomy_mode=autonomy_mode,
    )

    return {"proposal_body": proposal_body, "approved": approved}


def route_after_proposal(state: SchedulingState) -> str:
    if state.get("approved") is True:
        return "wait_for_selection"
    return "end"


async def wait_for_selection_node(state: SchedulingState) -> dict:
    """Pause until the Reply Handler provides the buyer's chosen slot.

    Resumes when Command(resume=slot_dict) is called with the selected slot.
    """
    selected_slot: dict = interrupt(
        {
            "type": "slot_selection",
            "store_name": state["store_name"],
            "available_slots": state["available_slots"][:3],
        }
    )
    return {"selected_slot": selected_slot}


async def book_node(state: SchedulingState) -> dict:
    """Create the Google Calendar event with a Meet link."""
    slot = state.get("selected_slot") or (state["available_slots"][0] if state["available_slots"] else {})
    if not slot:
        logger.error("scheduling_no_slot_to_book")
        return {"routing_action": "booking_failed"}

    result = await create_event(
        slot=slot,
        attendee_emails=[state["buyer_email"]],
        title=f"Wholesale intro call — {state['store_name']}",
        description=(
            f"30-minute wholesale partnership discovery call with {state['buyer_name']} "
            f"from {state['store_name']}."
        ),
    )

    logger.info(
        "scheduling_event_created",
        event_id=result["event_id"],
        meet_link=result["meet_link"],
    )
    return {"event_id": result["event_id"], "meet_link": result["meet_link"]}


async def confirm_node(state: SchedulingState) -> dict:
    """Format the confirmation email body (sent by email_service downstream)."""
    slot = state.get("selected_slot") or {}
    slot_display = _fmt_slot(slot) if slot else "your chosen time"

    confirmation = (
        f"Hi {state['buyer_name']},\n\n"
        f"Your call is confirmed for {slot_display}.\n\n"
        f"Join via Google Meet: {state['meet_link']}\n\n"
        "Looking forward to talking with you!"
    )
    logger.info("scheduling_confirmation_drafted", store_name=state["store_name"])
    return {"proposal_body": confirmation}


async def notify_node(state: SchedulingState) -> dict:
    """Send a WhatsApp alert to the founder confirming the booking."""
    slot = state.get("selected_slot") or {}
    slot_display = _fmt_slot(slot) if slot else "a chosen time"

    try:
        from app.services.whatsapp_service import send_deal_alert

        await send_deal_alert(
            phone=settings.whatsapp_founder_phone,
            store_name=state["store_name"],
            reply_summary=(
                f"Meeting booked with {state['buyer_name']} ({state['buyer_email']}) "
                f"for {slot_display}.\n"
                f"Meet link: {state['meet_link']}"
            ),
        )
    except Exception as exc:
        logger.warning("scheduling_notify_failed", error=str(exc))

    try:
        from app.services.crm_sync import CrmEventType, push_event

        await push_event(
            tenant_id=state.get("tenant_id", ""),
            event_type=CrmEventType.MEETING_BOOKED,
            event_data={
                "store_name": state.get("store_name", ""),
                "store_email": state.get("buyer_email", ""),
                "meeting_time": slot_display,
                "meeting_url": state.get("meet_link", ""),
            },
        )
    except Exception as exc:
        logger.warning("crm_sync_meeting_booked_failed", error=str(exc))

    return {"routing_action": "meeting_booked"}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_scheduling_graph(checkpointer=None):
    """Compile the Scheduling graph.

    Requires a checkpointer for the two interrupt() calls (propose_slots and
    wait_for_selection) to persist state across HTTP requests.
    """
    graph = StateGraph(SchedulingState)

    graph.add_node("guardrail", guardrail_node)
    graph.add_node("fetch_availability", fetch_availability_node)
    graph.add_node("propose_slots", propose_slots_node)
    graph.add_node("wait_for_selection", wait_for_selection_node)
    graph.add_node("book", book_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("notify", notify_node)

    graph.set_entry_point("guardrail")
    graph.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {"fetch_availability": "fetch_availability", "end": END},
    )
    graph.add_edge("fetch_availability", "propose_slots")
    graph.add_conditional_edges(
        "propose_slots",
        route_after_proposal,
        {"wait_for_selection": "wait_for_selection", "end": END},
    )
    graph.add_edge("wait_for_selection", "book")
    graph.add_edge("book", "confirm")
    graph.add_edge("confirm", "notify")
    graph.add_edge("notify", END)

    return graph.compile(checkpointer=checkpointer)
