"""Tests for the SchedulingAgent — guardrail, slot proposal, booking, notify."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from app.agents.scheduling_agent import (
    book_node,
    build_scheduling_graph,
    guardrail_node,
    notify_node,
)
from app.core.config import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLOTS = [
    {"start": "2026-06-10T09:00:00+00:00", "end": "2026-06-10T09:30:00+00:00"},
    {"start": "2026-06-10T10:00:00+00:00", "end": "2026-06-10T10:30:00+00:00"},
    {"start": "2026-06-10T14:00:00+00:00", "end": "2026-06-10T14:30:00+00:00"},
]


def _initial_state(
    lead_score: float = 9.0,
    explicit_request: bool = False,
    selected_slot: dict | None = None,
) -> dict[str, Any]:
    return {
        "lead_score": lead_score,
        "explicit_request": explicit_request,
        "buyer_email": "buyer@store.com",
        "buyer_name": "Jane Doe",
        "store_name": "Brooklyn Indie Boutique",
        "tenant_id": "tenant-1",
        "available_slots": list(_SLOTS),
        "selected_slot": selected_slot,
        "proposal_body": "",
        "approved": None,
        "event_id": "",
        "meet_link": "",
        "routing_action": "",
        "graph_thread_id": "test-thread",
    }


# ---------------------------------------------------------------------------
# Guardrail — unit tests (no graph needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guardrail_blocks_low_lead_score() -> None:
    state = _initial_state(lead_score=6.0, explicit_request=False)
    result = await guardrail_node(state)  # type: ignore[arg-type]
    assert result["routing_action"] == "blocked_by_guardrail"


@pytest.mark.asyncio
async def test_guardrail_blocks_exactly_at_threshold() -> None:
    # Rule is lead_score > 8.0 — equality does NOT pass
    state = _initial_state(lead_score=8.0, explicit_request=False)
    result = await guardrail_node(state)  # type: ignore[arg-type]
    assert result["routing_action"] == "blocked_by_guardrail"


@pytest.mark.asyncio
async def test_guardrail_allows_high_lead_score() -> None:
    state = _initial_state(lead_score=8.1, explicit_request=False)
    result = await guardrail_node(state)  # type: ignore[arg-type]
    assert result["routing_action"] == ""


@pytest.mark.asyncio
async def test_guardrail_allows_explicit_request_regardless_of_score() -> None:
    state = _initial_state(lead_score=4.0, explicit_request=True)
    result = await guardrail_node(state)  # type: ignore[arg-type]
    assert result["routing_action"] == ""


# ---------------------------------------------------------------------------
# Full graph — guardrail blocks → END, no HITL triggered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_blocked_goes_to_end_without_hitl() -> None:
    graph = build_scheduling_graph()  # no checkpointer needed — no interrupt reached
    state = _initial_state(lead_score=5.0, explicit_request=False)

    result = await graph.ainvoke(state)

    assert result["routing_action"] == "blocked_by_guardrail"
    assert "__interrupt__" not in result


# ---------------------------------------------------------------------------
# Full graph — high-value lead passes guardrail and hits HITL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_high_value_lead_hits_hitl() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_scheduling_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "sched-test-1"}}
    state = _initial_state(lead_score=9.0)

    with (
        patch("app.agents.scheduling_agent.get_free_slots", return_value=list(_SLOTS)),
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
    ):
        result = await graph.ainvoke(state, config=config)

    assert result["routing_action"] != "blocked_by_guardrail"
    assert len(result["available_slots"]) == 3
    assert "__interrupt__" in result


@pytest.mark.asyncio
async def test_full_graph_explicit_request_hits_hitl() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_scheduling_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "sched-test-2"}}
    state = _initial_state(lead_score=5.0, explicit_request=True)

    with (
        patch("app.agents.scheduling_agent.get_free_slots", return_value=list(_SLOTS)),
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
    ):
        result = await graph.ainvoke(state, config=config)

    assert "__interrupt__" in result


# ---------------------------------------------------------------------------
# book_node — creates event with Meet link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_book_node_creates_event_with_meet_link() -> None:
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(200, json={"access_token": "tok-test"})
    )
    respx.post(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    ).mock(
        return_value=Response(
            200,
            json={
                "id": "event-abc-123",
                "conferenceData": {
                    "entryPoints": [
                        {"uri": "https://meet.google.com/abc-defg-hij"}
                    ]
                },
            },
        )
    )

    state = _initial_state(selected_slot=_SLOTS[0])

    with patch.object(settings, "google_calendar_oauth_refresh_token", "fake-refresh"):
        result = await book_node(state)  # type: ignore[arg-type]

    assert result["event_id"] == "event-abc-123"
    assert result["meet_link"] == "https://meet.google.com/abc-defg-hij"


# ---------------------------------------------------------------------------
# notify_node — sends WhatsApp alert to founder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_node_sends_whatsapp_alert() -> None:
    state = _initial_state(selected_slot=_SLOTS[0])
    state["meet_link"] = "https://meet.google.com/abc-xyz"
    state["event_id"] = "event-123"

    mock_alert = AsyncMock()
    with patch("app.services.whatsapp_service.send_deal_alert", mock_alert):
        result = await notify_node(state)  # type: ignore[arg-type]

    mock_alert.assert_awaited_once()
    call_kwargs = mock_alert.call_args.kwargs
    assert "meet.google.com" in call_kwargs["reply_summary"]
    assert result["routing_action"] == "meeting_booked"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_availability_node_handles_calendar_api_failure() -> None:
    """Calendar API exception → node returns empty slots, does not propagate."""
    from app.agents.scheduling_agent import fetch_availability_node

    state = _initial_state(lead_score=9.0)

    with patch(
        "app.agents.scheduling_agent.get_free_slots",
        side_effect=Exception("Calendar API down"),
    ):
        result = await fetch_availability_node(state)  # type: ignore[arg-type]

    assert result["available_slots"] == []


@pytest.mark.asyncio
async def test_propose_slots_formats_gracefully_with_no_slots() -> None:
    """propose_slots_node formats a proposal even when available_slots is empty."""
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_scheduling_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "sched-empty-slots"}}
    state = _initial_state(lead_score=9.0)
    state["available_slots"] = []   # simulate calendar returning nothing

    with (
        patch("app.agents.scheduling_agent.get_free_slots", return_value=[]),
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
    ):
        result = await graph.ainvoke(state, config=config)

    # Graph pauses at HITL; proposal_body is in the interrupt payload (not yet
    # committed to state because the interrupted node hasn't returned yet)
    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload.get("proposal_preview", "") != ""


# ---------------------------------------------------------------------------
# get_free_slots — returns at least 3 slots from mocked calendar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_free_slots_returns_free_windows() -> None:
    from app.services.calendar_service import get_free_slots

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(200, json={"access_token": "tok-test"})
    )
    respx.post("https://www.googleapis.com/calendar/v3/freeBusy").mock(
        return_value=Response(
            200,
            json={"calendars": {"primary": {"busy": []}}},
        )
    )

    with patch.object(settings, "google_calendar_oauth_refresh_token", "fake-refresh"):
        slots = await get_free_slots(days_ahead=3, max_slots=10)

    assert len(slots) >= 3
    for slot in slots:
        assert "start" in slot and "end" in slot


# ---------------------------------------------------------------------------
# Security — Calendar service uses OAuth tokens, never passwords
# ---------------------------------------------------------------------------


def test_calendar_service_uses_oauth_not_passwords() -> None:
    calendar_fields = [
        f for f in vars(settings).keys() if "calendar" in f.lower()
    ]
    assert calendar_fields, "Expected Google Calendar config fields to exist"
    assert not any("password" in f for f in calendar_fields)

    import inspect

    import app.services.calendar_service as cal_svc

    source = inspect.getsource(cal_svc)
    assert "password=" not in source and '"password"' not in source, (
        "calendar_service.py must not use a password= argument or 'password' dict key"
    )
