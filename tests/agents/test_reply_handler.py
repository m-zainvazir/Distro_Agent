"""Tests for the ReplyHandlerAgent — classifier, graph routing, follow-up sequencer."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.reply_handler_agent import (
    INTERESTED,
    MEETING_REQUEST,
    NOT_INTERESTED,
    OBJECTION,
    build_reply_handler_graph,
    classify_intent,
)
from app.tasks.reply_tasks import _process_followup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(reply: str = "") -> dict:
    return {
        "reply_text": reply,
        "sender_email": "buyer@store.com",
        "gmail_thread_id": "thread-abc",
        "email_id": str(uuid.uuid4()),
        "tenant_id": "tenant-1",
        "intent": "",
        "routing_action": "",
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Classifier — all four intents + default
# ---------------------------------------------------------------------------


def test_classify_interested() -> None:
    text = (
        "Hi! I'd love to hear more about your products. "
        "Can you send me your wholesale catalog?"
    )
    assert classify_intent(text) == INTERESTED


def test_classify_objection() -> None:
    text = (
        "Your MOQ of 50 units is too high for a boutique our size. "
        "Do you offer a lower minimum order?"
    )
    assert classify_intent(text) == OBJECTION


def test_classify_not_interested() -> None:
    text = "Thanks for reaching out, but we're not interested at this time."
    assert classify_intent(text) == NOT_INTERESTED


def test_classify_meeting_request() -> None:
    text = "This sounds interesting! Can we schedule a call next week to discuss?"
    assert classify_intent(text) == MEETING_REQUEST


def test_classify_defaults_to_interested_for_generic_reply() -> None:
    # A polite but non-committal reply with no strong intent signals
    text = "Thank you for reaching out to us!"
    assert classify_intent(text) == INTERESTED


# ---------------------------------------------------------------------------
# Full graph — routing verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_routes_objection_to_negotiator() -> None:
    graph = build_reply_handler_graph()
    objection_text = (
        "Your pricing seems a bit expensive compared to what we currently carry. "
        "Concerned about the terms and shipping costs."
    )
    result = await graph.ainvoke(_state(reply=objection_text))

    assert result["intent"] == OBJECTION
    assert result["routing_action"] == "route_to_negotiator"


@pytest.mark.asyncio
async def test_full_graph_routes_meeting_request_to_scheduling() -> None:
    graph = build_reply_handler_graph()
    meeting_text = "Great! Let's set up a meeting — can we hop on a call this Thursday?"
    result = await graph.ainvoke(_state(reply=meeting_text))

    assert result["intent"] == MEETING_REQUEST
    assert result["routing_action"] == "route_to_scheduling"


@pytest.mark.asyncio
async def test_full_graph_routes_not_interested_to_lost() -> None:
    graph = build_reply_handler_graph()
    result = await graph.ainvoke(
        _state(reply="We're not interested, please remove us from your list.")
    )
    assert result["intent"] == NOT_INTERESTED
    assert result["routing_action"] == "mark_lead_lost"


@pytest.mark.asyncio
async def test_full_graph_routes_interested_to_send_catalog() -> None:
    graph = build_reply_handler_graph()
    result = await graph.ainvoke(
        _state(reply="This sounds great! Can you send me more information?")
    )
    assert result["intent"] == INTERESTED
    assert result["routing_action"] == "send_catalog"


# ---------------------------------------------------------------------------
# Follow-up sequencer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_sequencer_queues_hitl_on_first_followup() -> None:
    """Stale email with 0 prior follow-ups gets queued for HITL (pending_approval)."""
    email = MagicMock()
    email.id = uuid.uuid4()
    email.follow_up_count = 0
    email.outcome = "sent"
    db = AsyncMock()
    db.commit = AsyncMock()

    with patch("app.services.campaign_service.register_pending_approval") as mock_register:
        action = await _process_followup(email, db, tenant_id="tenant-abc")

    assert action == "queued"
    assert email.follow_up_count == 1
    assert email.outcome == "pending_approval"
    db.commit.assert_awaited_once()
    mock_register.assert_called_once_with(
        email_id=str(email.id),
        thread_id=f"followup-{email.id}",
        store_name="",
        graph_type="followup",
        tenant_id="tenant-abc",
    )


@pytest.mark.asyncio
async def test_followup_sequencer_marks_dormant_after_max_followups() -> None:
    """Email that has already had _MAX_FOLLOWUPS (2) is marked dormant — no register_pending."""
    email = MagicMock()
    email.id = uuid.uuid4()
    email.follow_up_count = 2
    email.outcome = "sent"
    db = AsyncMock()
    db.commit = AsyncMock()

    with patch("app.services.campaign_service.register_pending_approval") as mock_register:
        action = await _process_followup(email, db)

    assert action == "dormant"
    assert email.outcome == "ignored"
    db.commit.assert_awaited_once()
    mock_register.assert_not_called()


@pytest.mark.asyncio
async def test_followup_second_pass_queues_again() -> None:
    """Second follow-up (follow_up_count=1) is still queued, not dormant."""
    email = MagicMock()
    email.id = uuid.uuid4()
    email.follow_up_count = 1
    email.outcome = "sent"
    db = AsyncMock()
    db.commit = AsyncMock()

    with patch("app.services.campaign_service.register_pending_approval"):
        action = await _process_followup(email, db)

    assert action == "queued"
    assert email.follow_up_count == 2
    assert email.outcome == "pending_approval"


# ---------------------------------------------------------------------------
# Security — Gmail OAuth never stores passwords
# ---------------------------------------------------------------------------


def test_gmail_oauth_never_stores_passwords() -> None:
    """Verify no password field exists in Gmail-related config or service code."""
    from app.core.config import settings

    gmail_fields = [f for f in vars(settings).keys() if "gmail" in f.lower()]
    assert gmail_fields, "Expected Gmail config fields to exist"
    assert not any("password" in f for f in gmail_fields), (
        f"Found a password field in Gmail config: {gmail_fields}"
    )

    import inspect

    import app.services.gmail_service as svc

    source = inspect.getsource(svc)
    # No password= kwarg or password-keyed dict entry should appear in functional code.
    # The word "password" may appear in security-rule docstrings (e.g. "never store
    # passwords") — we check for the assignment/dict-key form only.
    assert "password=" not in source and '"password"' not in source, (
        "gmail_service.py must not use a password= argument or 'password' dict key"
    )
