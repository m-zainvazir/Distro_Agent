"""Tests for the RetentionAgent — sell-through math, guardrail, HITL, CRM emission."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.retention_agent import (
    assess_sellthrough,
    build_retention_graph,
    notify_node,
    route_after_assessment,
    route_after_pitch,
)
from app.services.crm_sync import CrmEventType

_NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)


def _state(**ov: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": "tenant-1",
        "store_name": "Brooklyn Indie Boutique",
        "buyer_email": "buyer@store.com",
        "buyer_name": "Jane Doe",
        "last_order_date": "2020-01-01",
        "units_ordered": 100,
        "avg_daily_sales": 1.0,
        "restock_threshold_pct": 20.0,
        "days_since_order": 0.0,
        "estimated_units_sold": 0.0,
        "estimated_remaining_units": 0.0,
        "sellthrough_pct": 0.0,
        "estimated_days_to_stockout": 0.0,
        "needs_restock": False,
        "restock_pitch": "",
        "approved": None,
        "routing_action": "",
        "graph_thread_id": "test-thread",
    }
    base.update(ov)
    return base


# ---------------------------------------------------------------------------
# assess_sellthrough — pure math
# ---------------------------------------------------------------------------


def test_restock_when_sold_through() -> None:
    # 110 days at 1/day on a 100-unit order → fully sold (capped) → restock.
    m = assess_sellthrough("2026-03-01", 100, 1.0, 20.0, now=_NOW)
    assert m["estimated_remaining_units"] == 0.0
    assert m["sellthrough_pct"] == 100.0
    assert m["needs_restock"] is True


def test_no_restock_when_stock_healthy() -> None:
    # 9 days at 1/day → 91 units left → healthy.
    m = assess_sellthrough("2026-06-10", 100, 1.0, 20.0, now=_NOW)
    assert m["estimated_remaining_units"] == 91.0
    assert m["sellthrough_pct"] == 9.0
    assert m["needs_restock"] is False


def test_threshold_boundary_is_inclusive() -> None:
    # 40 days at 2/day → 80 sold → exactly 20 left == threshold → restock.
    m = assess_sellthrough("2026-05-10", 100, 2.0, 20.0, now=_NOW)
    assert m["estimated_remaining_units"] == 20.0
    assert m["needs_restock"] is True


def test_just_above_threshold_no_restock() -> None:
    # 39 days at 2/day → 78 sold → 22 left > 20 → no restock.
    m = assess_sellthrough("2026-05-11", 100, 2.0, 20.0, now=_NOW)
    assert m["estimated_remaining_units"] == 22.0
    assert m["needs_restock"] is False


def test_zero_units_is_divide_safe() -> None:
    m = assess_sellthrough("2026-01-01", 0, 5.0, 20.0, now=_NOW)
    assert m["needs_restock"] is False


def test_zero_sales_rate_is_divide_safe() -> None:
    m = assess_sellthrough("2026-01-01", 100, 0.0, 20.0, now=_NOW)
    assert m["needs_restock"] is False
    assert m["sellthrough_pct"] == 0.0


def test_days_to_stockout_estimate() -> None:
    # 9 days at 1/day → 91 left → ~91 days to stockout.
    m = assess_sellthrough("2026-06-10", 100, 1.0, 20.0, now=_NOW)
    assert m["estimated_days_to_stockout"] == 91.0


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_route_after_assessment() -> None:
    assert route_after_assessment(_state(needs_restock=True)) == "draft_pitch"  # type: ignore[arg-type]
    assert route_after_assessment(_state(needs_restock=False)) == "end"  # type: ignore[arg-type]


def test_route_after_pitch() -> None:
    assert route_after_pitch(_state(approved=True)) == "notify"  # type: ignore[arg-type]
    assert route_after_pitch(_state(approved=False)) == "end"  # type: ignore[arg-type]
    assert route_after_pitch(_state(approved=None)) == "end"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Full graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_healthy_stock_ends_without_hitl() -> None:
    graph = build_retention_graph()  # no checkpointer — no interrupt is reached
    state = _state(last_order_date="2026-06-10", units_ordered=10000, avg_daily_sales=0.01)

    result = await graph.ainvoke(state)

    assert result["needs_restock"] is False
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_full_graph_low_stock_hits_hitl() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_retention_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "ret-1"}}
    state = _state(last_order_date="2020-01-01", units_ordered=100, avg_daily_sales=1.0)

    with (
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
    ):
        result = await graph.ainvoke(state, config=config)

    assert result["needs_restock"] is True
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "restock_pitch"
    assert payload["pitch_preview"]  # a pitch was drafted


@pytest.mark.asyncio
async def test_approval_emits_restock_crm_event() -> None:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    graph = build_retention_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "ret-2"}}
    state = _state(last_order_date="2020-01-01", units_ordered=100, avg_daily_sales=1.0)
    push = AsyncMock()

    with (
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.whatsapp_service.send_deal_alert", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
        patch("app.services.crm_sync.push_event", push),
    ):
        await graph.ainvoke(state, config=config)
        result = await graph.ainvoke(Command(resume=True), config=config)

    assert result["routing_action"] == "restock_pitched"
    push.assert_awaited_once()
    assert push.call_args.kwargs["event_type"] == CrmEventType.RESTOCK_OPPORTUNITY


@pytest.mark.asyncio
async def test_rejection_does_not_emit_crm_event() -> None:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    graph = build_retention_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "ret-3"}}
    state = _state(last_order_date="2020-01-01", units_ordered=100, avg_daily_sales=1.0)
    push = AsyncMock()

    with (
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
        patch("app.services.crm_sync.push_event", push),
    ):
        await graph.ainvoke(state, config=config)
        result = await graph.ainvoke(Command(resume=False), config=config)

    assert result.get("routing_action", "") != "restock_pitched"
    push.assert_not_awaited()


# ---------------------------------------------------------------------------
# notify_node — CRM payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_node_emits_restock_days() -> None:
    state = _state(
        needs_restock=True,
        sellthrough_pct=90.0,
        estimated_remaining_units=10.0,
        days_since_order=120.0,
    )
    push = AsyncMock()

    with (
        patch("app.services.whatsapp_service.send_deal_alert", new_callable=AsyncMock),
        patch("app.services.crm_sync.push_event", push),
    ):
        result = await notify_node(state)  # type: ignore[arg-type]

    assert result["routing_action"] == "restock_pitched"
    push.assert_awaited_once()
    kwargs = push.call_args.kwargs
    assert kwargs["event_type"] == CrmEventType.RESTOCK_OPPORTUNITY
    assert kwargs["event_data"]["restock_days"] == 120
    assert kwargs["event_data"]["store_name"] == "Brooklyn Indie Boutique"
