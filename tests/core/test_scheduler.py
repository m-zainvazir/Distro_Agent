"""In-process retention scheduler — enable/disable + one-shot sweep behavior."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.core.scheduler as scheduler


def test_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.settings, "retention_sweep_interval_hours", 0)
    assert scheduler.start_retention_scheduler() is None


@pytest.mark.asyncio
async def test_enabled_returns_task_and_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.settings, "retention_sweep_interval_hours", 24)
    task = scheduler.start_retention_scheduler()
    assert isinstance(task, asyncio.Task)
    # It should be sleeping (one interval) before the first sweep — not done yet.
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_run_sweep_once_invokes_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    swept = AsyncMock(return_value={"scanned": 2, "pitched": 1})

    class _Session:
        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    import app.core.database as db_mod
    import app.services.retention_trigger as rt

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(rt, "run_retention_sweep", swept)

    await scheduler._run_sweep_once()

    swept.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_sweep_once_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.database as db_mod

    def _boom() -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", _boom)

    # Must not raise — scheduler errors are logged and swallowed.
    await scheduler._run_sweep_once()
