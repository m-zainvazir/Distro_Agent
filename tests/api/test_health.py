"""Health endpoints + DB cold-start retry logic."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.api.health as health_mod
import app.core.database as db_mod
from app.api.health import router as health_router

_app = FastAPI()
_app.include_router(health_router)


def _make_session_factory(fail_first: int) -> Any:
    """Return an AsyncSessionLocal stand-in whose first *fail_first* SELECTs raise."""
    state = {"n": 0}

    class _Sess:
        async def execute(self, _q: Any) -> None:
            state["n"] += 1
            if state["n"] <= fail_first:
                raise OSError("connection refused")

    class _CM:
        async def __aenter__(self) -> _Sess:
            return _Sess()

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    return lambda: _CM()


# ---------------------------------------------------------------------------
# check_db retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_db_success_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", _make_session_factory(0))
    result = await db_mod.check_db()
    assert result["ok"] is True
    assert result["attempts"] == 1
    assert result["latency_ms"] is not None
    assert result["error"] is None


@pytest.mark.asyncio
async def test_check_db_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two cold-start failures, then the DB wakes — mirrors Neon resume.
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", _make_session_factory(2))
    sleep = AsyncMock()
    monkeypatch.setattr(db_mod.asyncio, "sleep", sleep)

    result = await db_mod.check_db(max_attempts=3, base_delay=0.01)

    assert result["ok"] is True
    assert result["attempts"] == 3
    assert sleep.await_count == 2  # backoff between the three attempts


@pytest.mark.asyncio
async def test_check_db_all_attempts_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", _make_session_factory(99))
    monkeypatch.setattr(db_mod.asyncio, "sleep", AsyncMock())

    result = await db_mod.check_db(max_attempts=2, base_delay=0.01)

    assert result["ok"] is False
    assert result["attempts"] == 2
    assert result["latency_ms"] is None
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_liveness_does_not_touch_db(monkeypatch: pytest.MonkeyPatch) -> None:
    # If /health touched the DB this would blow up; it must not.
    monkeypatch.setattr(
        health_mod, "check_db", AsyncMock(side_effect=AssertionError("should not be called"))
    )
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_db_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok() -> dict:
        return {"ok": True, "attempts": 1, "latency_ms": 4.2, "error": None}

    monkeypatch.setattr(health_mod, "check_db", _ok)
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
        resp = await client.get("/health/db")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["latency_ms"] == 4.2


@pytest.mark.asyncio
async def test_health_db_down_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _down() -> dict:
        return {"ok": False, "attempts": 3, "latency_ms": None, "error": "connection refused"}

    monkeypatch.setattr(health_mod, "check_db", _down)
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
        resp = await client.get("/health/db")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "down"
    assert body["error"] == "connection refused"
