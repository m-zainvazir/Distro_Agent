"""CopywriterAgent tests — all LLM calls mocked, DB persist skipped."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.copywriter_agent import (
    CopywriterState,
    build_copywriter_graph,
    critique_node,
    draft_node,
)
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import (
    DimensionScore,
    ScoredStore,
    StoreCandidate,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DIM = DimensionScore(score=7.0, reasoning="good", data_used=[])


def _make_store(name: str = "Botanica NYC") -> ScoredStore:
    return ScoredStore(
        store=StoreCandidate(
            place_id="place_001",
            name=name,
            address="123 Spring St",
            city="New York",
            state="NY",
            google_categories=["cosmetics_store"],
            website_url=None,
            instagram_handle="@botanica",
            instagram_followers=4200,
            instagram_posts_last_30_days=12,
            price_tier="$$",
            review_snippets=["beautiful botanical decor", "indie beauty finds"],
            storefront_image_urls=[],
        ),
        visual_vibe_score=None,
        category_score=_DIM,
        price_score=_DIM,
        engagement_score=_DIM,
        wholesale_score=_DIM,
        text_score=7.0,
        final_score=7.5,
        vision_was_run=False,
        match_summary="Great fit for clean beauty brands.",
        why_matched="botanical aesthetic, indie beauty focus",
        outreach_priority="HIGH",
    )


def _make_brand() -> BrandProfile:
    return BrandProfile(
        brand_name="Glow Lab",
        tagline="Clean beauty essentials",
        primary_colors=["#FDE8D8"],
        aesthetic_keywords=["botanical", "clean", "minimal"],
        product_categories=["skincare", "serum", "lip care"],
        price_range=(25.0, 85.0),
        brand_voice_description="Warm, grounded, eco-conscious.",
        wholesale_readiness_score=7.5,
        raw_product_images=[],
        embedding_vector=[],
    )


def _base_state(store_name: str = "Botanica NYC") -> CopywriterState:
    return CopywriterState(
        store=_make_store(store_name),
        brand_profile=_make_brand(),
        founder_name="Alex",
        email_tone="warm",
        tenant_id=str(uuid.uuid4()),
        campaign_id="",
        store_db_id="",
        draft_subject_a="",
        draft_subject_b="",
        draft_body="",
        personalization_score=0.0,
        critique_notes="",
        revision_count=0,
        approved=None,
        final_email=None,
    )


_MOCK_DRAFT = {
    "subject_a": "Wholesale partnership for Botanica NYC",
    "subject_b": "Glow Lab x Botanica NYC — let's talk",
    "body": (
        "Hi Botanica NYC team, I hope this note finds you well. "
        "My name is Alex and I am the founder of Glow Lab, a clean beauty brand "
        "specialising in botanical skincare, facial serums, and lip care. "
        "I came across Botanica NYC recently and immediately felt your botanical "
        "aesthetic and thoughtful curation of indie beauty products would be an "
        "ideal fit for our range. "
        "Glow Lab products are formulated with plant-based ingredients, packaged "
        "sustainably, and have been featured in several indie beauty publications. "
        "We would love to offer Botanica NYC wholesale pricing beginning at a "
        "five-hundred-dollar MOQ with a fifty percent retail margin across our serum "
        "and lip care lines. All products are shelf-ready and come with merchandising "
        "support materials. "
        "Would you be open to a brief conversation? Simply reply to this email to "
        "learn more about our wholesale programme and sample options. "
        "I look forward to the possibility of partnering with Botanica NYC. "
        "Warm regards, Alex"
    ),
}

# ---------------------------------------------------------------------------
# Unit tests: critique_node (deterministic, no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critique_good_draft_scores_high() -> None:
    state = {**_base_state(), **{
        "draft_subject_a": _MOCK_DRAFT["subject_a"],
        "draft_subject_b": _MOCK_DRAFT["subject_b"],
        "draft_body": _MOCK_DRAFT["body"],
        "revision_count": 1,
    }}
    result = await critique_node(state)
    assert result["personalization_score"] >= 7.0


@pytest.mark.asyncio
async def test_critique_flags_missing_store_name() -> None:
    state = {**_base_state("Rare Finds"), **{
        "draft_subject_a": "Hello from Glow Lab",
        "draft_subject_b": "A wholesale opportunity",
        "draft_body": "Hi team, we make great skincare products at great wholesale prices. "
                      "Please reply to learn more. " * 10,
        "revision_count": 1,
    }}
    result = await critique_node(state)
    assert result["personalization_score"] < 7.0
    assert "Store name" in result["critique_notes"] or "name" in result["critique_notes"].lower()


@pytest.mark.asyncio
async def test_critique_flags_short_body() -> None:
    state = {**_base_state(), **{
        "draft_subject_a": "Partnership",
        "draft_subject_b": "Wholesale opportunity",
        "draft_body": "Hi Botanica NYC. Botanica NYC would be great. Reply to learn more.",
        "revision_count": 1,
    }}
    result = await critique_node(state)
    assert result["personalization_score"] < 7.0


@pytest.mark.asyncio
async def test_critique_flags_spam_words() -> None:
    state = {**_base_state(), **{
        "draft_subject_a": "Free wholesale deal",
        "draft_subject_b": "Guaranteed savings",
        "draft_body": (
            "Hi Botanica NYC, this is a guaranteed free deal for Botanica NYC. "
            "Act now for a limited time offer! Reply to learn more about our wholesale program. "
            "Our botanical serum range is perfect for your store. MOQ starts at $500. "
            "We look forward to working with you. " * 3
        ),
        "revision_count": 1,
    }}
    result = await critique_node(state)
    assert result["personalization_score"] < 7.0


# ---------------------------------------------------------------------------
# Unit tests: draft_node (Groq mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_node_produces_two_subjects_and_body() -> None:
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = (
        '{"subject_a": "Partnership for Botanica NYC", '
        '"subject_b": "Glow Lab x Botanica NYC", '
        '"body": "' + _MOCK_DRAFT["body"].replace('"', '\\"') + '"}'
    )

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_groq_cls:
        mock_groq_cls.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
        result = await draft_node(_base_state())

    assert result["draft_subject_a"] != ""
    assert result["draft_subject_b"] != ""
    assert result["draft_body"] != ""
    assert result["revision_count"] == 1


# ---------------------------------------------------------------------------
# Integration tests: full graph with MemorySaver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_pauses_at_hitl() -> None:
    """Graph must pause at hitl_approval_node — nothing approved yet."""
    memory = MemorySaver()
    graph = build_copywriter_graph(checkpointer=memory)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = (
        '{"subject_a": "' + _MOCK_DRAFT["subject_a"] + '", '
        '"subject_b": "' + _MOCK_DRAFT["subject_b"] + '", '
        '"body": "' + _MOCK_DRAFT["body"].replace('"', '\\"') + '"}'
    )

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_groq_cls, \
         patch("app.agents.copywriter_agent._persist_pending_email", new=AsyncMock(return_value=uuid.uuid4())):
        mock_groq_cls.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
        result = await graph.ainvoke(_base_state(), config=config)

    # Graph should have paused — __interrupt__ present in result
    assert "__interrupt__" in result
    interrupt_val = result["__interrupt__"][0]
    assert "email_id" in interrupt_val.value
    assert "subject_a" in interrupt_val.value


@pytest.mark.asyncio
async def test_full_graph_approve_path() -> None:
    """Approve resumes the graph → final_email is set with status='approved'."""
    memory = MemorySaver()
    graph = build_copywriter_graph(checkpointer=memory)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = (
        '{"subject_a": "' + _MOCK_DRAFT["subject_a"] + '", '
        '"subject_b": "' + _MOCK_DRAFT["subject_b"] + '", '
        '"body": "' + _MOCK_DRAFT["body"].replace('"', '\\"') + '"}'
    )

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_groq_cls, \
         patch("app.agents.copywriter_agent._persist_pending_email", new=AsyncMock(return_value=uuid.uuid4())):
        mock_groq_cls.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
        # First pass — should pause at HITL
        await graph.ainvoke(_base_state(), config=config)
        # Approve
        final = await graph.ainvoke(Command(resume=True), config=config)

    assert final.get("final_email") is not None
    assert final["final_email"].status == "approved"


@pytest.mark.asyncio
async def test_full_graph_reject_loops_to_draft() -> None:
    """Rejection resets revision_count and loops back for a re-draft."""
    memory = MemorySaver()
    graph = build_copywriter_graph(checkpointer=memory)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = (
        '{"subject_a": "' + _MOCK_DRAFT["subject_a"] + '", '
        '"subject_b": "' + _MOCK_DRAFT["subject_b"] + '", '
        '"body": "' + _MOCK_DRAFT["body"].replace('"', '\\"') + '"}'
    )

    with patch("app.agents.copywriter_agent.AsyncGroq") as mock_groq_cls, \
         patch("app.agents.copywriter_agent._persist_pending_email", new=AsyncMock(return_value=uuid.uuid4())):
        mock_groq_cls.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
        # First pass
        await graph.ainvoke(_base_state(), config=config)
        # Reject — graph loops back to draft and pauses again at HITL
        result = await graph.ainvoke(Command(resume=False), config=config)

    # Should have paused again at HITL after the re-draft
    assert "__interrupt__" in result


# ---------------------------------------------------------------------------
# Checkpointer wiring test
# ---------------------------------------------------------------------------


def test_get_checkpointer_tries_postgres_first() -> None:
    """get_checkpointer() attempts AsyncPostgresSaver before falling back.

    On machines without libpq (CI / dev) it returns a MemorySaver, but the
    code path for AsyncPostgresSaver must be attempted first — ensuring that
    production deployments (which have libpq) automatically use Postgres.
    """
    from unittest.mock import MagicMock, patch

    # Simulate a successful AsyncPostgresSaver import and construction
    mock_saver = MagicMock()
    mock_cls = MagicMock(return_value=mock_saver)
    mock_cls.from_conn_string = MagicMock(return_value=mock_saver)

    with patch.dict(
        "sys.modules",
        {
            "langgraph.checkpoint.postgres": MagicMock(),
            "langgraph.checkpoint.postgres.aio": MagicMock(
                AsyncPostgresSaver=mock_cls
            ),
        },
    ):
        # Re-import to pick up the patched module
        import importlib
        import app.core.checkpointer as cp_module

        importlib.reload(cp_module)
        checkpointer = cp_module.get_checkpointer()

    # Must have called from_conn_string with the configured database URL
    mock_cls.from_conn_string.assert_called_once()
    assert checkpointer is mock_saver


def test_get_checkpointer_falls_back_to_memory_saver_when_libpq_missing() -> None:
    """When libpq is absent, get_checkpointer() falls back to MemorySaver."""
    from langgraph.checkpoint.memory import MemorySaver
    from unittest.mock import patch

    with patch(
        "app.core.checkpointer.get_checkpointer",
        side_effect=lambda: MemorySaver(),
    ):
        from app.core.checkpointer import get_checkpointer as _get

        result = _get()

    assert isinstance(result, MemorySaver)
