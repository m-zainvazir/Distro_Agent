"""Tests for the CopywriterAgent — critique, draft, HITL graph flow, and checkpointer."""
from __future__ import annotations

import json
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models.user  # noqa: F401 — registers User mapper for Tenant.users relationship
from app.agents.copywriter_agent import (
    build_copywriter_graph,
    critique_node,
    draft_node,
)
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import DimensionScore, ScoredStore, StoreCandidate

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_GOOD_BODY = (
    "Hi Brooklyn Indie Boutique team, we are reaching out from SkinGlow because "
    "your store's unique aesthetic and carefully curated selection of artisan products "
    "is exactly what we look for in our ideal wholesale partners. "
    "Brooklyn Indie Boutique has a wonderful reputation for celebrating independent "
    "makers and bringing their authentic stories to your thriving local community of "
    "conscious consumers. Our Glow Serum is a bestselling skincare product that aligns "
    "perfectly with your clean beauty focus and natural wellness vibe. "
    "We offer wholesale terms starting at a minimum order quantity of twelve units with "
    "competitive pricing tiers that work well for independent boutiques exactly like yours. "
    "We warmly invite you to learn more about our growing partnership program and explore "
    "how SkinGlow can complement your existing product collection. "
    "Please reply to this email and we will send over our full wholesale catalog along "
    "with complimentary product samples for your careful consideration. "
    "Looking forward to connecting with your team very soon."
)

_GOOD_DRAFT: dict[str, str] = {
    "subject_a": "Wholesale opportunity for Brooklyn Indie Boutique",
    "subject_b": "Brooklyn Indie Boutique x SkinGlow partnership",
    "body": _GOOD_BODY,
}


def _store() -> ScoredStore:
    return ScoredStore(
        store=StoreCandidate(
            place_id="place123",
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
        category_score=DimensionScore(score=8.0, reasoning="good match", data_used=[]),
        price_score=DimensionScore(score=7.5, reasoning="aligned", data_used=[]),
        engagement_score=DimensionScore(score=7.0, reasoning="active", data_used=[]),
        wholesale_score=DimensionScore(score=8.5, reasoning="wholesale ready", data_used=[]),
        text_score=7.75,
        final_score=7.75,
        vision_was_run=False,
        match_summary="Great match",
        why_matched="natural artisan wellness boutique store",
        outreach_priority="HIGH",
    )


def _brand() -> BrandProfile:
    return BrandProfile(
        brand_name="SkinGlow",
        tagline="Glow naturally",
        primary_colors=["white", "gold"],
        aesthetic_keywords=["clean", "minimal", "natural"],
        product_categories=["skincare", "serum"],
        price_range=(25.0, 150.0),
        brand_voice_description="Warm, authentic, wellness-focused",
        wholesale_readiness_score=8.5,
        raw_product_images=[],
        embedding_vector=[0.1] * 384,
    )


def _initial_state() -> dict[str, Any]:
    return {
        "store": _store(),
        "brand_profile": _brand(),
        "founder_name": "Alex Smith",
        "email_tone": "warm",
        "tenant_id": "tenant-123",
        "campaign_id": "",
        "store_db_id": "",
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


def _make_groq_mock(mock_cls: MagicMock, draft: dict[str, str] = _GOOD_DRAFT) -> None:
    mock_instance = AsyncMock()
    mock_cls.return_value = mock_instance
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(draft)
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage = None  # prevents MagicMock arithmetic in token tracking
    mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)


# ---------------------------------------------------------------------------
# Critique node — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critique_good_draft_scores_high() -> None:
    state: dict[str, Any] = {
        **_initial_state(),
        "draft_subject_a": "Wholesale opportunity for Brooklyn Indie Boutique",
        "draft_subject_b": "Brooklyn Indie Boutique x SkinGlow partnership",
        "draft_body": _GOOD_BODY,
    }
    result = await critique_node(state)  # type: ignore[arg-type]
    assert result["personalization_score"] >= 7.0


@pytest.mark.asyncio
async def test_critique_flags_missing_store_name() -> None:
    # Replace second occurrence so name only appears once
    body_one_mention = _GOOD_BODY.replace(
        "Brooklyn Indie Boutique has a wonderful", "The boutique has a wonderful", 1
    )
    state: dict[str, Any] = {
        **_initial_state(),
        "draft_subject_a": "Wholesale for Brooklyn Indie Boutique",
        "draft_subject_b": "SkinGlow x Brooklyn partnership",
        "draft_body": body_one_mention,
    }
    result = await critique_node(state)  # type: ignore[arg-type]
    assert result["personalization_score"] < 8.0
    assert "Store name appears" in result["critique_notes"]


@pytest.mark.asyncio
async def test_critique_flags_short_body() -> None:
    state: dict[str, Any] = {
        **_initial_state(),
        "draft_subject_a": "Wholesale for Brooklyn Indie Boutique",
        "draft_subject_b": "SkinGlow x Brooklyn Indie Boutique deal",
        "draft_body": (
            "Hi Brooklyn Indie Boutique team, we would love to work with Brooklyn Indie "
            "Boutique on a wholesale partnership. Please reply to learn more. "
            "We offer great MOQ and pricing tiers. Looking forward to connecting soon."
        ),
    }
    result = await critique_node(state)  # type: ignore[arg-type]
    assert result["personalization_score"] < 9.0
    assert "short" in result["critique_notes"].lower()


@pytest.mark.asyncio
async def test_critique_flags_spam_words() -> None:
    # Inject a clear spam word: "urgent" as a standalone word (word-boundary check)
    spam_body = _GOOD_BODY.replace("warmly invite", "invite") + " Urgent: respond soon."
    state: dict[str, Any] = {
        **_initial_state(),
        "draft_subject_a": "Wholesale for Brooklyn Indie Boutique",
        "draft_subject_b": "Brooklyn Indie Boutique x SkinGlow",
        "draft_body": spam_body,
    }
    result = await critique_node(state)  # type: ignore[arg-type]
    assert result["personalization_score"] < 9.0
    assert "urgent" in result["critique_notes"].lower()


# ---------------------------------------------------------------------------
# Draft node — unit test (Groq mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_node_produces_two_subjects_and_body() -> None:
    state = _initial_state()
    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_cls:
        _make_groq_mock(mock_cls)
        result = await draft_node(state)  # type: ignore[arg-type]

    assert result["draft_subject_a"]
    assert result["draft_subject_b"]
    assert result["draft_body"]
    assert result["revision_count"] == 1


@pytest.mark.asyncio
async def test_draft_node_falls_back_on_groq_failure() -> None:
    """All 3 Groq attempts fail → fallback body returned, no exception raised."""
    state = _initial_state()
    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.chat.completions.create = AsyncMock(
            side_effect=Exception("Groq API unavailable")
        )
        result = await draft_node(state)  # type: ignore[arg-type]

    assert result["draft_body"] != ""
    assert result["draft_subject_a"] != ""
    assert result["revision_count"] == 1
    # Token state unchanged on failure
    assert result["token_usage"] == {"input": 0, "output": 0}
    assert result["cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_critique_node_handles_empty_why_matched() -> None:
    """critique_node must not crash when why_matched is an empty string."""
    state: dict[str, Any] = {
        **_initial_state(),
        "draft_subject_a": "Wholesale for Brooklyn Indie Boutique",
        "draft_subject_b": "Brooklyn Indie Boutique x SkinGlow",
        "draft_body": _GOOD_BODY,
    }
    # Override store with empty why_matched
    from app.models.store_candidate import DimensionScore, ScoredStore, StoreCandidate

    state["store"] = ScoredStore(
        store=StoreCandidate(
            place_id="p1",
            name="Brooklyn Indie Boutique",
            address="123 Main",
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
        category_score=DimensionScore(score=8.0, reasoning="ok", data_used=[]),
        price_score=DimensionScore(score=7.0, reasoning="ok", data_used=[]),
        engagement_score=DimensionScore(score=7.0, reasoning="ok", data_used=[]),
        wholesale_score=DimensionScore(score=7.0, reasoning="ok", data_used=[]),
        text_score=7.5,
        final_score=7.5,
        vision_was_run=False,
        match_summary="",
        why_matched="",   # empty — should not crash
        outreach_priority="HIGH",
    )
    result = await critique_node(state)  # type: ignore[arg-type]
    # Empty why_matched means vibe check is skipped (vibe_words is empty list)
    assert "personalization_score" in result


# ---------------------------------------------------------------------------
# Full graph — integration tests (MemorySaver checkpointer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_pauses_at_hitl() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_copywriter_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "test-hitl-1"}}

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_cls, \
         patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock), \
         patch("app.services.campaign_service.register_pending"):
        _make_groq_mock(mock_cls)
        result = await graph.ainvoke(_initial_state(), config=config)

    assert "__interrupt__" in result


@pytest.mark.asyncio
async def test_full_graph_approve_path() -> None:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    checkpointer = MemorySaver()
    graph = build_copywriter_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "test-approve-1"}}

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_cls, \
         patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock), \
         patch("app.services.campaign_service.register_pending"):
        _make_groq_mock(mock_cls)
        result1 = await graph.ainvoke(_initial_state(), config=config)

    assert "__interrupt__" in result1

    with patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock), \
         patch("app.services.campaign_service.register_pending"):
        result2 = await graph.ainvoke(Command(resume=True), config=config)

    assert result2.get("final_email") is not None
    assert result2["final_email"].status == "approved"


@pytest.mark.asyncio
async def test_full_graph_reject_loops_to_draft() -> None:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    checkpointer = MemorySaver()
    graph = build_copywriter_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "test-reject-1"}}

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_cls, \
         patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock), \
         patch("app.services.campaign_service.register_pending"):
        _make_groq_mock(mock_cls)
        result1 = await graph.ainvoke(_initial_state(), config=config)

    assert "__interrupt__" in result1

    # Reject — should loop back to draft, re-draft, and hit interrupt again
    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_cls2, \
         patch("app.services.whatsapp_service.send_approval_card", new_callable=AsyncMock), \
         patch("app.services.campaign_service.register_pending"):
        _make_groq_mock(mock_cls2)
        result2 = await graph.ainvoke(Command(resume=False), config=config)

    assert "__interrupt__" in result2


# ---------------------------------------------------------------------------
# Checkpointer factory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_checkpointer_tries_postgres_first() -> None:
    from app.core.checkpointer import get_checkpointer

    mock_saver = MagicMock(spec=object)  # spec=object means no __aenter__, so not treated as a CM
    mock_saver_cls = MagicMock()
    mock_saver_cls.from_conn_string.return_value = mock_saver

    mock_module = MagicMock()
    mock_module.AsyncPostgresSaver = mock_saver_cls

    with patch.dict(sys.modules, {"langgraph.checkpoint.postgres.aio": mock_module}):
        result = await get_checkpointer()

    mock_saver_cls.from_conn_string.assert_called_once()
    assert result is mock_saver


@pytest.mark.asyncio
async def test_get_checkpointer_falls_back_to_memory_saver_when_libpq_missing() -> None:
    from app.core.checkpointer import get_checkpointer
    from langgraph.checkpoint.memory import MemorySaver

    # Setting the module to None in sys.modules causes ImportError on import.
    with patch.dict(sys.modules, {"langgraph.checkpoint.postgres.aio": None}):
        result = await get_checkpointer()

    assert isinstance(result, MemorySaver)


# ---------------------------------------------------------------------------
# _persist_pending_email — multi-tenant tenant_id is always set (NOT NULL column)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_pending_email_sets_tenant_id(monkeypatch: Any) -> None:
    from app.agents.copywriter_agent import _persist_pending_email

    captured: dict = {}

    class _Sess:
        async def __aenter__(self) -> "_Sess":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

        def add(self, rec: Any) -> None:
            captured["rec"] = rec

        async def commit(self) -> None:
            return None

    monkeypatch.setattr("app.core.database.AsyncSessionLocal", lambda: _Sess())

    tid, cid, sid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    state = {
        **_initial_state(),
        "tenant_id": tid,
        "campaign_id": cid,
        "store_db_id": sid,
        "draft_subject_a": "Subject",
        "draft_body": "Body",
    }

    await _persist_pending_email(state)  # type: ignore[arg-type]

    assert "rec" in captured  # DB path was taken (campaign_id + store_db_id set)
    assert str(captured["rec"].tenant_id) == tid
    assert str(captured["rec"].campaign_id) == cid
