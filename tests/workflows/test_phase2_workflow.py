"""Tests for the Phase 2 master orchestration workflow.

Strategy
--------
- Node-level tests call each async node function directly (no graph needed).
- Graph-level tests use MemorySaver + patch sub-agent factories to avoid real
  LLM / DB / SendGrid calls.  They verify the graph pauses at the right HITL
  points and routes each intent correctly.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.models.brand_profile import BrandProfile
from app.models.outreach import OutreachEmailDraft
from app.models.store_candidate import DimensionScore, ScoredStore, StoreCandidate
from app.workflows.phase2_workflow import (
    PHASE_DISPATCH_FAILED,
    PHASE_DORMANT,
    PHASE_DRAFT_REJECTED,
    PHASE_EMAIL_SENT,
    PHASE_LOST,
    PHASE_NEGOTIATING,
    PHASE_SCHEDULING,
    PHASE_WON,
    build_phase2_graph,
    classify_reply_node,
    dispatch_email_node,
    draft_rejected_node,
    handle_interested_node,
    handle_no_reply_node,
    mark_lost_node,
    route_after_copywriter,
    route_by_intent,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _store(final_score: float = 9.0) -> ScoredStore:
    return ScoredStore(
        store=StoreCandidate(
            place_id="place-abc",
            name="Brooklyn Indie Boutique",
            address="123 Main St",
            city="Brooklyn",
            state="NY",
            google_categories=["gift_shop"],
            website_url=None,
            instagram_handle=None,
            instagram_followers=None,
            instagram_posts_last_30_days=None,
            storefront_image_urls=[],
            price_tier="$$",
            review_snippets=[],
        ),
        visual_vibe_score=None,
        category_score=DimensionScore(score=8.0, reasoning="match", data_used=[]),
        price_score=DimensionScore(score=7.5, reasoning="ok", data_used=[]),
        engagement_score=DimensionScore(score=7.0, reasoning="active", data_used=[]),
        wholesale_score=DimensionScore(score=8.5, reasoning="ready", data_used=[]),
        text_score=7.75,
        final_score=final_score,
        vision_was_run=False,
        match_summary="Great match",
        why_matched="natural artisan wellness boutique",
        outreach_priority="HIGH",
    )


def _brand() -> BrandProfile:
    return BrandProfile(
        brand_name="SkinGlow",
        tagline="Glow naturally",
        primary_colors=["white", "gold"],
        aesthetic_keywords=["clean", "minimal", "natural"],
        product_categories=["skincare"],
        price_range=(25.0, 150.0),
        brand_voice_description="Warm, authentic",
        wholesale_readiness_score=8.5,
        raw_product_images=[],
        embedding_vector=[0.1] * 384,
    )


def _approved_email() -> OutreachEmailDraft:
    return OutreachEmailDraft(
        subject_a="Wholesale opportunity for Brooklyn Indie Boutique",
        subject_b="Brooklyn Indie Boutique x SkinGlow",
        body="Hi team, we'd love to partner with your boutique...",
        personalization_score=8.0,
    )


def _initial_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": "tenant-1",
        "brand_profile": _brand(),
        "store": _store(),
        "founder_name": "Alex Smith",
        "email_tone": "warm",
        "campaign_id": "campaign-abc",
        "store_db_id": "store-db-1",
        "buyer_email": "buyer@store.com",
        "buyer_name": "Jane Doe",
        "approved_email": None,
        "copywriter_thread_id": "",
        "outreach_email_id": "",
        "email_sent": False,
        "reply_text": "",
        "sender_email": "",
        "gmail_thread_id": "",
        "reply_intent": "",
        "negotiation_thread_id": "",
        "scheduling_thread_id": "",
        "meet_link": "",
        "phase": "",
        "follow_up_count": 0,
        "errors": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Routing functions — unit tests
# ---------------------------------------------------------------------------


def test_route_after_copywriter_approved() -> None:
    state = _initial_state(approved_email=_approved_email())
    assert route_after_copywriter(state) == "dispatch_email"  # type: ignore[arg-type]


def test_route_after_copywriter_rejected() -> None:
    state = _initial_state(approved_email=None)
    assert route_after_copywriter(state) == "draft_rejected"  # type: ignore[arg-type]


def test_route_by_intent_all_branches() -> None:
    for intent, expected in [
        ("INTERESTED", "handle_interested"),
        ("OBJECTION", "invoke_negotiator"),
        ("NOT_INTERESTED", "mark_lost"),
        ("MEETING_REQUEST", "invoke_scheduler"),
    ]:
        assert route_by_intent(_initial_state(reply_text="hello", reply_intent=intent)) == expected  # type: ignore[arg-type]


def test_route_by_intent_empty_reply_goes_to_no_reply() -> None:
    assert route_by_intent(_initial_state(reply_text="")) == "handle_no_reply"  # type: ignore[arg-type]


def test_route_by_intent_unknown_intent_defaults_to_interested() -> None:
    assert route_by_intent(_initial_state(reply_text="hi", reply_intent="UNKNOWN")) == "handle_interested"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Node unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_reply_node_identifies_interested() -> None:
    state = _initial_state(reply_text="I'd love to hear more about your wholesale program!")
    result = await classify_reply_node(state)  # type: ignore[arg-type]
    assert result["reply_intent"] == "INTERESTED"


@pytest.mark.asyncio
async def test_classify_reply_node_empty_text_returns_blank() -> None:
    result = await classify_reply_node(_initial_state(reply_text=""))  # type: ignore[arg-type]
    assert result["reply_intent"] == ""


@pytest.mark.asyncio
async def test_handle_interested_node_sets_phase_won() -> None:
    result = await handle_interested_node(_initial_state())  # type: ignore[arg-type]
    assert result["phase"] == PHASE_WON


@pytest.mark.asyncio
async def test_mark_lost_node_sets_phase_lost() -> None:
    result = await mark_lost_node(_initial_state())  # type: ignore[arg-type]
    assert result["phase"] == PHASE_LOST


@pytest.mark.asyncio
async def test_handle_no_reply_sets_phase_dormant() -> None:
    result = await handle_no_reply_node(_initial_state(follow_up_count=1))  # type: ignore[arg-type]
    assert result["phase"] == PHASE_DORMANT
    assert result["follow_up_count"] == 1


@pytest.mark.asyncio
async def test_draft_rejected_node_sets_phase() -> None:
    result = await draft_rejected_node(_initial_state())  # type: ignore[arg-type]
    assert result["phase"] == PHASE_DRAFT_REJECTED


@pytest.mark.asyncio
async def test_dispatch_email_node_no_approved_email_returns_failed() -> None:
    result = await dispatch_email_node(_initial_state(approved_email=None))  # type: ignore[arg-type]
    assert result["email_sent"] is False
    assert result["phase"] == PHASE_DISPATCH_FAILED
    assert any("no approved email" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_dispatch_email_node_sends_and_returns_email_id() -> None:
    email_id = "email-uuid-123"
    with patch(
        "app.workflows.phase2_workflow._dispatch_draft",
        new_callable=AsyncMock,
        return_value=email_id,
    ):
        result = await dispatch_email_node(  # type: ignore[arg-type]
            _initial_state(approved_email=_approved_email())
        )
    assert result["email_sent"] is True
    assert result["outreach_email_id"] == email_id
    assert result["phase"] == PHASE_EMAIL_SENT


@pytest.mark.asyncio
async def test_dispatch_email_node_handles_send_failure() -> None:
    with patch(
        "app.workflows.phase2_workflow._dispatch_draft",
        side_effect=RuntimeError("SendGrid down"),
    ):
        result = await dispatch_email_node(  # type: ignore[arg-type]
            _initial_state(approved_email=_approved_email())
        )
    assert result["email_sent"] is False
    assert result["phase"] == PHASE_DISPATCH_FAILED
    assert any("SendGrid down" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Full graph — routing tests
# ---------------------------------------------------------------------------


def _mock_copywriter_graph(approved: OutreachEmailDraft | None = None) -> MagicMock:
    """Return a mock copywriter sub-graph that immediately returns with final_email."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock(
        return_value={"final_email": approved, "cost_usd": 0.0, "token_usage": {"input": 0, "output": 0}}
    )
    return mock


@pytest.mark.asyncio
async def test_full_graph_rejected_draft_goes_to_end() -> None:
    """When copywriter returns no final_email, graph ends with phase=draft_rejected."""
    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-rejected-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(None)),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
    ):
        result = await graph.ainvoke(_initial_state(), config=config)

    assert result["phase"] == PHASE_DRAFT_REJECTED
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_full_graph_pauses_at_await_reply_after_dispatch() -> None:
    """Happy path: copywriter approves → email sent → graph pauses for reply."""
    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-happy-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-1"),
    ):
        result = await graph.ainvoke(_initial_state(), config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "await_reply"
    assert payload["store_name"] == "Brooklyn Indie Boutique"


@pytest.mark.asyncio
async def test_full_graph_interested_reply_sets_won() -> None:
    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-interested-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-2"),
    ):
        await graph.ainvoke(_initial_state(), config=config)
        result = await graph.ainvoke(
            Command(resume={
                "reply_text": "I'd love to hear more about your wholesale program!",
                "sender_email": "buyer@store.com",
                "gmail_thread_id": "thread-1",
            }),
            config=config,
        )

    assert result["phase"] == PHASE_WON


@pytest.mark.asyncio
async def test_full_graph_not_interested_reply_sets_lost() -> None:
    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-lost-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-3"),
    ):
        await graph.ainvoke(_initial_state(), config=config)
        result = await graph.ainvoke(
            Command(resume={
                "reply_text": "Thanks but we're not interested at this time.",
                "sender_email": "buyer@store.com",
                "gmail_thread_id": "thread-2",
            }),
            config=config,
        )

    assert result["phase"] == PHASE_LOST


@pytest.mark.asyncio
async def test_full_graph_empty_reply_sets_dormant() -> None:
    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-dormant-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-4"),
    ):
        await graph.ainvoke(_initial_state(), config=config)
        result = await graph.ainvoke(
            Command(resume={"reply_text": "", "sender_email": "", "gmail_thread_id": ""}),
            config=config,
        )

    assert result["phase"] == PHASE_DORMANT


@pytest.mark.asyncio
async def test_full_graph_objection_reply_invokes_negotiator() -> None:
    """OBJECTION intent triggers invoke_negotiator_node; graph ends negotiating."""
    mock_neg_graph = MagicMock()
    mock_neg_graph.ainvoke = AsyncMock(
        return_value={"routing_action": "negotiator_pending", "final_counter": None}
    )

    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-objection-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.agents.negotiator_agent.build_negotiator_graph", return_value=mock_neg_graph),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-5"),
    ):
        await graph.ainvoke(_initial_state(), config=config)
        result = await graph.ainvoke(
            Command(resume={
                "reply_text": "Your MOQ is too high for our boutique size.",
                "sender_email": "buyer@store.com",
                "gmail_thread_id": "thread-3",
            }),
            config=config,
        )

    assert result["phase"] == PHASE_NEGOTIATING
    assert result["negotiation_thread_id"] != ""


@pytest.mark.asyncio
async def test_full_graph_meeting_request_invokes_scheduler() -> None:
    """MEETING_REQUEST intent triggers invoke_scheduler_node."""
    mock_sched_graph = MagicMock()
    mock_sched_graph.ainvoke = AsyncMock(
        return_value={"meet_link": "", "routing_action": "blocked_by_guardrail"}
    )

    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-meeting-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.agents.scheduling_agent.build_scheduling_graph", return_value=mock_sched_graph),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-6"),
    ):
        await graph.ainvoke(_initial_state(), config=config)
        result = await graph.ainvoke(
            Command(resume={
                "reply_text": "Can we hop on a call to discuss?",
                "sender_email": "buyer@store.com",
                "gmail_thread_id": "thread-4",
            }),
            config=config,
        )

    assert result["phase"] == PHASE_SCHEDULING
    assert result["scheduling_thread_id"] != ""


# ---------------------------------------------------------------------------
# Tenant isolation — tenant_id must flow into every sub-agent invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_negotiator_receives_correct_tenant_id() -> None:
    """tenant_id from Phase2State is passed into the NegotiatorState."""
    captured: list[dict] = []

    async def _fake_ainvoke(state: Any, config: Any = None) -> dict:
        captured.append(dict(state) if isinstance(state, dict) else {})
        return {"routing_action": "", "final_counter": None}

    mock_neg_graph = MagicMock()
    mock_neg_graph.ainvoke = _fake_ainvoke

    graph = build_phase2_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "p2-tenant-1"}}

    with (
        patch("app.agents.copywriter_agent.build_copywriter_graph", return_value=_mock_copywriter_graph(_approved_email())),
        patch("app.agents.negotiator_agent.build_negotiator_graph", return_value=mock_neg_graph),
        patch("app.core.checkpointer.get_checkpointer", new_callable=AsyncMock, return_value=MemorySaver()),
        patch("app.workflows.phase2_workflow._dispatch_draft", new_callable=AsyncMock, return_value="email-7"),
    ):
        await graph.ainvoke(_initial_state(tenant_id="acme-tenant"), config=config)
        await graph.ainvoke(
            Command(resume={
                "reply_text": "Your price is too high.",
                "sender_email": "b@store.com",
                "gmail_thread_id": "t5",
            }),
            config=config,
        )

    assert len(captured) >= 1
    assert captured[0].get("tenant_id") == "acme-tenant"
