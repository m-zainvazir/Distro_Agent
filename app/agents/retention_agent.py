"""RetentionAgent — monitors retailer sell-through and pitches restock orders (Layer 10).

Flow
----
assess_sellthrough → route_after_assessment
    ├── END  (stock still healthy — not yet time to restock)
    └── draft_pitch [HITL] → route_after_pitch
            ├── END  (founder rejected the pitch)
            └── notify → END   (alert founder + emit RESTOCK_OPPORTUNITY CRM event)

The assessment is deterministic (no LLM / no external call): given the last order
size, an estimated daily sell-through rate, and how long ago the order shipped, it
estimates remaining stock and flags a restock when stock falls to/below the threshold.
The restock pitch is warm outreach to an existing buyer, so it is gated as
ROUTINE_OUTREACH (auto-sends under semi_auto / full_auto, interrupts in assist).
"""
from __future__ import annotations

from datetime import datetime, timezone

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.hitl_gate import ROUTINE_OUTREACH, request_human_approval
from app.core.config import settings
from app.core.logging import logger

_DEFAULT_RESTOCK_THRESHOLD_PCT = 20.0  # restock when ≤ this % of the order remains

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class RetentionState(TypedDict):
    tenant_id: str
    store_name: str
    buyer_email: str
    buyer_name: str
    last_order_date: str          # ISO 8601 date the last wholesale order shipped
    units_ordered: int            # size of that last order
    avg_daily_sales: float        # estimated sell-through rate (units/day)
    restock_threshold_pct: float  # restock when remaining ≤ this % of the order

    # ── Computed by assess_sellthrough ───────────────────────────────────────
    days_since_order: float
    estimated_units_sold: float
    estimated_remaining_units: float
    sellthrough_pct: float
    estimated_days_to_stockout: float
    needs_restock: bool

    # ── Pitch / HITL ─────────────────────────────────────────────────────────
    restock_pitch: str
    approved: bool | None
    routing_action: str
    graph_thread_id: str          # LangGraph thread_id for HITL resume routing


# ---------------------------------------------------------------------------
# Pure assessment helper (no I/O — easy to unit-test)
# ---------------------------------------------------------------------------


def assess_sellthrough(
    last_order_date: str,
    units_ordered: int,
    avg_daily_sales: float,
    restock_threshold_pct: float = _DEFAULT_RESTOCK_THRESHOLD_PCT,
    now: datetime | None = None,
) -> dict:
    """Estimate remaining stock for a retailer's last order and whether to restock.

    Divide-by-zero safe: a non-positive order size or sell-through rate never
    triggers a restock.
    """
    now = now or datetime.now(timezone.utc)

    order_dt = datetime.fromisoformat(last_order_date)
    if order_dt.tzinfo is None:
        order_dt = order_dt.replace(tzinfo=timezone.utc)
    days_since_order = max((now - order_dt).total_seconds() / 86400.0, 0.0)

    if units_ordered <= 0 or avg_daily_sales <= 0:
        return {
            "days_since_order": round(days_since_order, 2),
            "estimated_units_sold": 0.0,
            "estimated_remaining_units": float(max(units_ordered, 0)),
            "sellthrough_pct": 0.0,
            "estimated_days_to_stockout": 0.0,
            "needs_restock": False,
        }

    units_sold = min(avg_daily_sales * days_since_order, float(units_ordered))
    remaining = units_ordered - units_sold
    sellthrough_pct = units_sold / units_ordered * 100.0
    days_to_stockout = remaining / avg_daily_sales
    needs_restock = remaining <= units_ordered * (restock_threshold_pct / 100.0)

    return {
        "days_since_order": round(days_since_order, 2),
        "estimated_units_sold": round(units_sold, 2),
        "estimated_remaining_units": round(remaining, 2),
        "sellthrough_pct": round(sellthrough_pct, 1),
        "estimated_days_to_stockout": round(days_to_stockout, 1),
        "needs_restock": needs_restock,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def assess_sellthrough_node(state: RetentionState) -> dict:
    """Estimate sell-through and decide whether a restock pitch is due."""
    threshold = state.get("restock_threshold_pct") or _DEFAULT_RESTOCK_THRESHOLD_PCT
    metrics = assess_sellthrough(
        last_order_date=state["last_order_date"],
        units_ordered=state["units_ordered"],
        avg_daily_sales=state["avg_daily_sales"],
        restock_threshold_pct=threshold,
    )
    logger.info(
        "retention_assessed",
        store_name=state["store_name"],
        sellthrough_pct=metrics["sellthrough_pct"],
        remaining=metrics["estimated_remaining_units"],
        needs_restock=metrics["needs_restock"],
    )
    return metrics


def route_after_assessment(state: RetentionState) -> str:
    return "draft_pitch" if state.get("needs_restock") else "end"


async def draft_pitch_node(state: RetentionState) -> dict:
    """Compose a restock pitch and pause for founder HITL approval."""
    remaining = int(round(state.get("estimated_remaining_units", 0.0)))
    days_left = int(round(state.get("estimated_days_to_stockout", 0.0)))
    sellthrough = state.get("sellthrough_pct", 0.0)

    pitch = (
        f"Hi {state['buyer_name']},\n\n"
        f"Hope {state['store_name']} is doing great! Based on the pace your last order "
        f"has been moving, you're at roughly {sellthrough:.0f}% sell-through — about "
        f"{remaining} units left, likely ~{days_left} days of stock at the current rate.\n\n"
        "Want me to line up a restock so you don't run dry? I can keep the same "
        "wholesale terms as last time and get it on its way this week.\n\n"
        "Just reply and I'll send the updated order over."
    )

    logger.info("retention_hitl_requested", store_name=state["store_name"])

    try:
        from app.services.campaign_service import register_pending
        from app.services.whatsapp_service import send_approval_card

        restock_id = f"restock-{state['store_name']}"
        register_pending(
            restock_id,
            state.get("graph_thread_id", "unknown"),
            state["store_name"],
            graph_type="retention",
            tenant_id=state.get("tenant_id", ""),
        )
        await send_approval_card(
            phone=settings.whatsapp_founder_phone,
            email_preview=pitch[:300],
            email_id=restock_id,
        )
    except Exception as exc:
        logger.warning("retention_whatsapp_failed", error=str(exc))

    from app.services.tenant_service import get_autonomy_mode

    autonomy_mode = await get_autonomy_mode(state.get("tenant_id", ""))
    approved: bool = request_human_approval(
        {
            "type": "restock_pitch",
            "store_name": state["store_name"],
            "buyer_email": state["buyer_email"],
            "sellthrough_pct": sellthrough,
            "estimated_remaining_units": remaining,
            "pitch_preview": pitch[:400],
        },
        action_class=ROUTINE_OUTREACH,
        autonomy_mode=autonomy_mode,
    )

    return {"restock_pitch": pitch, "approved": approved}


def route_after_pitch(state: RetentionState) -> str:
    return "notify" if state.get("approved") is True else "end"


async def notify_node(state: RetentionState) -> dict:
    """Alert the founder and emit the RESTOCK_OPPORTUNITY CRM event."""
    try:
        from app.services.whatsapp_service import send_deal_alert

        await send_deal_alert(
            phone=settings.whatsapp_founder_phone,
            store_name=state["store_name"],
            reply_summary=(
                f"Restock pitch approved for {state['buyer_name']} "
                f"({state['buyer_email']}) — "
                f"{state.get('sellthrough_pct', 0.0):.0f}% sold through, "
                f"~{int(round(state.get('estimated_remaining_units', 0.0)))} units left."
            ),
        )
    except Exception as exc:
        logger.warning("retention_notify_failed", error=str(exc))

    try:
        from app.services.crm_sync import CrmEventType, push_event

        await push_event(
            tenant_id=state.get("tenant_id", ""),
            event_type=CrmEventType.RESTOCK_OPPORTUNITY,
            event_data={
                "store_name": state.get("store_name", ""),
                "store_email": state.get("buyer_email", ""),
                "restock_days": int(round(state.get("days_since_order", 0.0))),
            },
        )
    except Exception as exc:
        logger.warning("crm_sync_restock_failed", error=str(exc))

    return {"routing_action": "restock_pitched"}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_retention_graph(checkpointer=None):
    """Compile the Retention graph.

    Requires a checkpointer for the draft_pitch HITL interrupt() to persist
    state across HTTP requests (resumed via the campaigns approve/reject endpoints).
    """
    graph = StateGraph(RetentionState)

    graph.add_node("assess_sellthrough", assess_sellthrough_node)
    graph.add_node("draft_pitch", draft_pitch_node)
    graph.add_node("notify", notify_node)

    graph.set_entry_point("assess_sellthrough")
    graph.add_conditional_edges(
        "assess_sellthrough",
        route_after_assessment,
        {"draft_pitch": "draft_pitch", "end": END},
    )
    graph.add_conditional_edges(
        "draft_pitch",
        route_after_pitch,
        {"notify": "notify", "end": END},
    )
    graph.add_edge("notify", END)

    return graph.compile(checkpointer=checkpointer)
