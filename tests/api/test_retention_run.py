"""Retention sweep service + POST /retention/run cron endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.agents.retention_agent as ra
import app.api.v1.retention as retention_mod
import app.core.checkpointer as ck
import app.services.retention_trigger as rt
from app.api.v1.retention import router as retention_router
from app.core.database import get_db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _email(deal_status: str = "deal_closed") -> MagicMock:
    e = MagicMock()
    e.id = uuid.uuid4()
    e.tenant_id = uuid.uuid4()
    e.to_email = "buyer@store.com"
    e.updated_at = datetime(2026, 1, 1)
    e.deal_status = deal_status
    return e


def _store(name: str = "Indie Boutique") -> MagicMock:
    s = MagicMock()
    s.name = name
    return s


def _db(rows: list[tuple]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _fake_graph(result: dict) -> MagicMock:
    g = MagicMock()
    g.ainvoke = AsyncMock(return_value=result)
    return g


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, graph_result: dict) -> None:
    async def _ck() -> object:
        return object()

    monkeypatch.setattr(ck, "get_checkpointer", _ck)
    monkeypatch.setattr(
        ra, "build_retention_graph", lambda checkpointer=None: _fake_graph(graph_result)
    )


# ---------------------------------------------------------------------------
# run_retention_sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_marks_pitched_when_graph_interrupts(monkeypatch: pytest.MonkeyPatch) -> None:
    email, store = _email(), _store()
    db = _db([(email, store)])
    _patch_runtime(monkeypatch, {"__interrupt__": [object()]})  # HITL pause = pitch in flight

    summary = await rt.run_retention_sweep(db)

    assert summary == {"scanned": 1, "pitched": 1}
    assert email.deal_status == "restock_pitched"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_marks_pitched_under_full_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    email, store = _email(), _store()
    db = _db([(email, store)])
    # full_auto runs straight through to notify (no interrupt) and sets routing_action.
    _patch_runtime(monkeypatch, {"routing_action": "restock_pitched"})

    summary = await rt.run_retention_sweep(db)

    assert summary["pitched"] == 1
    assert email.deal_status == "restock_pitched"


@pytest.mark.asyncio
async def test_sweep_leaves_not_yet_due_deal(monkeypatch: pytest.MonkeyPatch) -> None:
    email, store = _email(), _store()
    db = _db([(email, store)])
    _patch_runtime(monkeypatch, {"routing_action": "", "needs_restock": False})

    summary = await rt.run_retention_sweep(db)

    assert summary == {"scanned": 1, "pitched": 0}
    assert email.deal_status == "deal_closed"  # untouched → re-evaluated next sweep
    db.commit.assert_not_awaited()  # nothing changed


@pytest.mark.asyncio
async def test_sweep_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db([])
    _patch_runtime(monkeypatch, {})
    summary = await rt.run_retention_sweep(db)
    assert summary == {"scanned": 0, "pitched": 0}


# ---------------------------------------------------------------------------
# POST /retention/run — cron token gate
# ---------------------------------------------------------------------------

_app = FastAPI()
_app.include_router(retention_router, prefix="/api/v1")


async def _override_db() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock()


@pytest.mark.asyncio
async def test_run_endpoint_503_when_token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retention_mod.settings, "cron_token", "")
    _app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        resp = await c.post("/api/v1/retention/run", headers={"X-Cron-Token": "anything"})
    _app.dependency_overrides.clear()
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_run_endpoint_403_on_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retention_mod.settings, "cron_token", "secret")
    _app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        resp = await c.post("/api/v1/retention/run", headers={"X-Cron-Token": "wrong"})
    _app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_run_endpoint_runs_sweep_with_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retention_mod.settings, "cron_token", "secret")
    monkeypatch.setattr(
        rt, "run_retention_sweep", AsyncMock(return_value={"scanned": 3, "pitched": 2})
    )
    _app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        resp = await c.post("/api/v1/retention/run", headers={"X-Cron-Token": "secret"})
    _app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "scanned": 3, "pitched": 2}
