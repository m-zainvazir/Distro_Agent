"""POST /campaigns/start — launches the Phase 2 workflow as background tasks.

DB and the Phase 2 graph are mocked; these tests verify the endpoint loads
tenant-scoped inputs, creates a campaign, schedules one background run per
store, and that the runner + resume wiring register/resume a `phase2` approval.
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.services.campaign_launch as launch
from app.api.v1.campaigns import router as campaigns_router
from app.core.database import get_db
from app.core.dependencies import get_current_tenant
from app.models.brand_profile import BrandProfile
from app.models.campaign import BrandProfileRecord, StoreCandidate, Tenant
from app.models.store_candidate import ScoredStore

_test_app = FastAPI()
_test_app.include_router(campaigns_router, prefix="/api/v1")


class _FakeInterrupt:
    def __init__(self, value: dict) -> None:
        self.value = value


def _make_mock_db(campaign_id: uuid.UUID) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def _refresh(obj: Any) -> None:
        obj.id = campaign_id

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _brand_profile() -> BrandProfile:
    return BrandProfile(
        brand_name="SkinGlow",
        tagline="",
        primary_colors=[],
        aesthetic_keywords=["clean"],
        product_categories=[],
        price_range=(25.0, 150.0),
        brand_voice_description="",
        wholesale_readiness_score=0.0,
        raw_product_images=[],
        embedding_vector=[0.1] * 8,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_campaign_launches_phase2(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = Tenant(id=uuid.uuid4(), name="Acme")
    campaign_id = uuid.uuid4()
    db = _make_mock_db(campaign_id)

    brand_rec = BrandProfileRecord(id=uuid.uuid4(), tenant_id=tenant.id, brand_name="SkinGlow")
    stores = [
        StoreCandidate(id=uuid.uuid4(), tenant_id=tenant.id, name="Indie Boutique"),
        StoreCandidate(id=uuid.uuid4(), tenant_id=tenant.id, name="Corner Shop"),
    ]

    async def _fake_load(_db: Any, _tid: str, _bid: str, _sids: list[str]) -> tuple:
        return brand_rec, stores

    run_calls: list[dict] = []

    async def _fake_run(**kwargs: Any) -> str:
        run_calls.append(kwargs)
        return "email-xyz"

    monkeypatch.setattr(launch, "load_campaign_inputs", _fake_load)
    monkeypatch.setattr(launch, "record_to_brand_profile", lambda _rec: _brand_profile())
    monkeypatch.setattr(launch, "record_to_scored_store", lambda _s: MagicMock(spec=ScoredStore))
    monkeypatch.setattr(launch, "run_phase2_for_store", _fake_run)

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_tenant] = lambda: tenant
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/campaigns/start",
            json={
                "brand_profile_id": str(brand_rec.id),
                "store_ids": [str(s.id) for s in stores],
                "email_tone": "warm",
            },
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 202
    payload = resp.json()
    assert payload["campaign_id"] == str(campaign_id)
    assert payload["stores_launched"] == 2
    db.commit.assert_awaited()
    # Background tasks run after the response — one Phase 2 run per store.
    assert len(run_calls) == 2
    assert {c["store_db_id"] for c in run_calls} == {str(s.id) for s in stores}
    assert all(c["campaign_id"] == str(campaign_id) for c in run_calls)


@pytest.mark.asyncio
async def test_seed_demo_creates_brand_and_store_for_tenant() -> None:
    tenant = Tenant(id=uuid.uuid4(), name="Acme")

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def _refresh(obj: Any) -> None:
        # Assign a fresh id per row so brand and store get distinct ids.
        obj.id = uuid.uuid4()

    db.refresh = AsyncMock(side_effect=_refresh)

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_tenant] = lambda: tenant
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/campaigns/seed-demo")
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 201
    payload = resp.json()
    assert payload["brand_profile_id"]
    assert len(payload["store_ids"]) == 1
    assert payload["store_ids"][0] != payload["brand_profile_id"]
    # One brand row + one store row added, then committed.
    assert db.add.call_count == 2
    db.commit.assert_awaited()
    added = {type(c.args[0]).__name__ for c in db.add.call_args_list}
    assert added == {"BrandProfileRecord", "StoreCandidate"}


@pytest.mark.asyncio
async def test_start_campaign_brand_not_found_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = Tenant(id=uuid.uuid4(), name="Acme")
    db = _make_mock_db(uuid.uuid4())

    async def _fake_load(*_args: Any, **_kwargs: Any) -> tuple:
        raise LookupError("brand_profile not found for this tenant")

    monkeypatch.setattr(launch, "load_campaign_inputs", _fake_load)

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_tenant] = lambda: tenant
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/campaigns/start",
            json={"brand_profile_id": str(uuid.uuid4()), "store_ids": [str(uuid.uuid4())]},
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 404
    db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_phase2_for_store_registers_phase2_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(
        return_value={"__interrupt__": [_FakeInterrupt({"email_id": "email-1"})]}
    )

    async def _fake_checkpointer() -> object:
        return object()

    registered: dict = {}

    def _fake_register(**kwargs: Any) -> None:
        registered.update(kwargs)

    # Patch the symbols where they are looked up (imported inside the function).
    import app.core.checkpointer as ck
    import app.services.campaign_service as svc
    import app.workflows.phase2_workflow as wf

    monkeypatch.setattr(ck, "get_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(wf, "build_phase2_graph", lambda checkpointer=None: fake_graph)
    monkeypatch.setattr(svc, "register_pending_approval", _fake_register)

    store = MagicMock(spec=ScoredStore)
    store.store = MagicMock()
    store.store.name = "Indie Boutique"

    email_id = await launch.run_phase2_for_store(
        tenant_id="t1",
        campaign_id="c1",
        brand_profile=_brand_profile(),
        scored_store=store,
        store_db_id="s1",
        buyer_email="buyer@store.com",
        buyer_name="Indie Boutique",
        founder_name="Alex",
        email_tone="warm",
    )

    assert email_id == "email-1"
    assert registered["graph_type"] == "phase2"
    assert registered["email_id"] == "email-1"
    assert registered["thread_id"] == "phase2-c1-s1"
    assert registered["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_run_phase2_for_store_no_pause_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value={"phase": "email_sent"})

    async def _fake_checkpointer() -> object:
        return object()

    import app.core.checkpointer as ck
    import app.services.campaign_service as svc
    import app.workflows.phase2_workflow as wf

    register_called = {"n": 0}
    monkeypatch.setattr(ck, "get_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(wf, "build_phase2_graph", lambda checkpointer=None: fake_graph)
    monkeypatch.setattr(
        svc,
        "register_pending_approval",
        lambda **_k: register_called.__setitem__("n", register_called["n"] + 1),
    )

    store = MagicMock(spec=ScoredStore)
    store.store = MagicMock()
    store.store.name = "Indie Boutique"

    email_id = await launch.run_phase2_for_store(
        tenant_id="t1",
        campaign_id="c1",
        brand_profile=_brand_profile(),
        scored_store=store,
        store_db_id="s1",
        buyer_email="",
        buyer_name="Indie Boutique",
        founder_name="Alex",
        email_tone="warm",
    )

    assert email_id == ""
    assert register_called["n"] == 0


# ---------------------------------------------------------------------------
# Resume wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_routes_phase2_to_master_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langgraph.types import Command

    import app.core.resume as resume_mod
    import app.workflows.phase2_workflow as wf

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value={})

    monkeypatch.setattr(
        resume_mod,
        "get_pending_approval",
        lambda _eid: {"thread_id": "phase2-c1-s1", "graph_type": "phase2", "tenant_id": "t1"},
    )
    removed: list[str] = []
    monkeypatch.setattr(resume_mod, "remove_pending_approval", lambda eid: removed.append(eid))
    monkeypatch.setattr(wf, "build_phase2_graph", lambda checkpointer=None: fake_graph)

    async def _fake_checkpointer() -> object:
        return object()

    import app.core.checkpointer as ck

    monkeypatch.setattr(ck, "get_checkpointer", _fake_checkpointer)

    await resume_mod.resume_graph_for_email(email_id="email-1", approved=True)

    fake_graph.ainvoke.assert_awaited_once()
    args, kwargs = fake_graph.ainvoke.call_args
    assert isinstance(args[0], Command)
    assert args[0].resume is True
    assert kwargs["config"]["configurable"]["thread_id"] == "phase2-c1-s1"
    assert removed == ["email-1"]


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def test_record_to_brand_profile_maps_fields() -> None:
    rec = BrandProfileRecord(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        brand_name="SkinGlow",
        aesthetic_keywords=["clean", "minimal"],
        price_range_min=25.0,
        price_range_max=150.0,
        embedding_vector=[0.2] * 4,
    )
    profile = launch.record_to_brand_profile(rec)
    assert profile.brand_name == "SkinGlow"
    assert profile.aesthetic_keywords == ["clean", "minimal"]
    assert profile.price_range == (25.0, 150.0)
    assert profile.embedding_vector == [0.2] * 4


def test_record_to_scored_store_carries_lead_score() -> None:
    store = StoreCandidate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Indie Boutique",
        address="1 Main St",
        google_place_id="place-1",
        lead_score=8.4,
        vibe_score=7.0,
    )
    scored = launch.record_to_scored_store(store)
    assert scored.store.name == "Indie Boutique"
    assert scored.store.place_id == "place-1"
    assert scored.final_score == 8.4
    assert scored.outreach_priority == "HIGH"
