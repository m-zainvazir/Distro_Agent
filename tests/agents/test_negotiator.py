"""Tests for the NegotiatorAgent — objection parsing, rulebook checks, graph routing."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.negotiator_agent import (
    MOQ,
    NET_TERMS,
    OTHER,
    PRICE,
    SHIPPING,
    _check_within_rulebook,
    _classify_objection_type,
    build_negotiator_graph,
)
from app.models.rulebook import WholesaleRulebook

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rulebook(**overrides: Any) -> WholesaleRulebook:
    defaults: dict[str, Any] = {
        "min_order_quantity": 12,
        "wholesale_discount_max_pct": 50.0,
        "net_payment_days_max": 30,
        "free_shipping_threshold": 500.0,
        "non_negotiables": ["consignment", "sale-or-return"],
    }
    defaults.update(overrides)
    return WholesaleRulebook(**defaults)


def _initial_state(
    objection_text: str,
    rulebook: WholesaleRulebook | None = None,
) -> dict[str, Any]:
    return {
        "objection_text": objection_text,
        "buyer_email": "buyer@store.com",
        "original_email_id": str(uuid.uuid4()),
        "tenant_id": "tenant-123",
        "rulebook": rulebook or _rulebook(),
        "objection_type": "",
        "within_rulebook": True,
        "escalation_reason": "",
        "counter_offer_body": "",
        "counter_id": "",
        "revision_count": 0,
        "approved": None,
        "final_counter": None,
        "routing_action": "",
        "token_usage": {"input": 0, "output": 0},
        "cost_usd": 0.0,
    }


def _mock_groq(mock_cls: MagicMock, counter: str = "We can offer 40% off on orders of 12+ units.") -> None:
    mock_instance = AsyncMock()
    mock_cls.return_value = mock_instance
    mock_choice = MagicMock()
    mock_choice.message.content = counter
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage = None  # prevents MagicMock arithmetic in token tracking
    mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)


# ---------------------------------------------------------------------------
# Objection type classifier — all 4 known types
# ---------------------------------------------------------------------------


def test_classify_objection_price() -> None:
    text = "Your prices are too expensive for our margin to work out."
    assert _classify_objection_type(text) == PRICE


def test_classify_objection_moq() -> None:
    text = "Your MOQ of 50 units is far too high for a boutique our size."
    assert _classify_objection_type(text) == MOQ


def test_classify_objection_shipping() -> None:
    text = "The shipping cost is prohibitive for our small initial order."
    assert _classify_objection_type(text) == SHIPPING


def test_classify_objection_net_terms() -> None:
    text = "We need Net 60 payment terms to manage our cash flow properly."
    assert _classify_objection_type(text) == NET_TERMS


def test_classify_objection_defaults_to_other() -> None:
    text = "We have some questions about your product packaging materials."
    assert _classify_objection_type(text) == OTHER


# ---------------------------------------------------------------------------
# Rulebook boundary checks
# ---------------------------------------------------------------------------


def test_check_rulebook_within_limits_for_valid_discount() -> None:
    rb = _rulebook(wholesale_discount_max_pct=50.0)
    within, reason = _check_within_rulebook(PRICE, "Can you offer 40% off retail?", rb)
    assert within is True
    assert reason == ""


def test_check_rulebook_exceeds_discount_max_escalates() -> None:
    rb = _rulebook(wholesale_discount_max_pct=50.0)
    within, reason = _check_within_rulebook(
        PRICE, "We need 60% off retail to make our margin work.", rb
    )
    assert within is False
    assert "60%" in reason


def test_check_rulebook_moq_below_minimum_escalates() -> None:
    rb = _rulebook(min_order_quantity=12)
    within, reason = _check_within_rulebook(
        MOQ, "We can only order 6 units to start.", rb
    )
    assert within is False
    assert "6" in reason


def test_check_rulebook_net_terms_within_limit() -> None:
    rb = _rulebook(net_payment_days_max=30)
    within, reason = _check_within_rulebook(
        NET_TERMS, "Could you do Net 30 payment terms?", rb
    )
    assert within is True


def test_check_rulebook_net_terms_exceeds_limit_escalates() -> None:
    rb = _rulebook(net_payment_days_max=30)
    within, reason = _check_within_rulebook(
        NET_TERMS, "We require Net 60 for all new vendors.", rb
    )
    assert within is False
    assert "60" in reason


def test_check_rulebook_non_negotiable_escalates_regardless_of_type() -> None:
    rb = _rulebook(non_negotiables=["consignment", "sale-or-return"])
    within, reason = _check_within_rulebook(
        PRICE, "Can you do consignment for the first order?", rb
    )
    assert within is False
    assert "consignment" in reason.lower()


def test_check_rulebook_shipping_always_within_limits() -> None:
    rb = _rulebook(free_shipping_threshold=500.0)
    within, reason = _check_within_rulebook(
        SHIPPING, "The shipping fee is too high for us.", rb
    )
    assert within is True


def test_check_rulebook_other_always_escalates() -> None:
    rb = _rulebook()
    within, reason = _check_within_rulebook(
        OTHER, "We have a question about your exclusivity terms.", rb
    )
    assert within is False
    assert "OTHER" in reason or "founder" in reason.lower()


# ---------------------------------------------------------------------------
# Full graph — within rulebook → HITL interrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_within_rulebook_drafts_counter_and_hits_hitl() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_negotiator_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "neg-hitl-1"}}

    state = _initial_state(
        objection_text="Can you offer 40% off retail pricing for us?",
        rulebook=_rulebook(wholesale_discount_max_pct=50.0),
    )

    with (
        patch("app.agents.negotiator_agent.AsyncGroq") as mock_cls,
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
    ):
        _mock_groq(mock_cls)
        result = await graph.ainvoke(state, config=config)

    assert result["objection_type"] == PRICE
    assert result["within_rulebook"] is True
    assert result["counter_offer_body"] != ""
    assert "__interrupt__" in result


# ---------------------------------------------------------------------------
# Full graph — outside rulebook → escalates, no HITL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_outside_rulebook_escalates_no_counter() -> None:
    # No checkpointer needed — escalate path never hits interrupt()
    with patch("app.services.whatsapp_service.send_deal_alert", new_callable=AsyncMock):
        graph = build_negotiator_graph()
        state = _initial_state(
            objection_text="We need at least 60% off retail, otherwise the margins don't work.",
            rulebook=_rulebook(wholesale_discount_max_pct=50.0),
        )
        result = await graph.ainvoke(state)

    assert result["within_rulebook"] is False
    assert result["routing_action"] == "escalated_to_founder"
    assert "__interrupt__" not in result
    assert result["counter_offer_body"] == ""  # no draft was attempted


# ---------------------------------------------------------------------------
# Full graph — approve path → final_counter set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_approve_path_sets_final_counter() -> None:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    checkpointer = MemorySaver()
    graph = build_negotiator_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "neg-approve-1"}}

    state = _initial_state(
        objection_text="Can you do 40% off retail pricing?",
        rulebook=_rulebook(wholesale_discount_max_pct=50.0),
    )

    with (
        patch("app.agents.negotiator_agent.AsyncGroq") as mock_cls,
        patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock),
        patch("app.services.campaign_service.register_pending"),
    ):
        _mock_groq(mock_cls, counter="We can offer 40% off on orders of 12+ units.")
        result1 = await graph.ainvoke(state, config=config)

    assert "__interrupt__" in result1

    result2 = await graph.ainvoke(Command(resume=True), config=config)

    assert result2.get("final_counter") is not None
    assert result2["routing_action"] == "counter_approved"


# ---------------------------------------------------------------------------
# Error path — Groq fails, fallback counter returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_counter_falls_back_on_groq_failure() -> None:
    """All 3 Groq attempts raise → fallback counter returned, no exception propagated."""
    from app.agents.negotiator_agent import draft_counter_node

    state = _initial_state(
        objection_text="Can you offer 40% off retail?",
        rulebook=_rulebook(wholesale_discount_max_pct=50.0),
    )
    state["objection_type"] = PRICE

    with patch("app.agents.negotiator_agent.AsyncGroq") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        mock_instance.chat.completions.create = AsyncMock(
            side_effect=Exception("Groq API unavailable")
        )
        result = await draft_counter_node(state)  # type: ignore[arg-type]

    assert result["counter_offer_body"] != ""
    assert result["revision_count"] == 1
    # Token state unchanged on failure
    assert result["token_usage"] == {"input": 0, "output": 0}
    assert result["cost_usd"] == 0.0
