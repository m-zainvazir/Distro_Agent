"""Tests for the LangGraph checkpointer factory.

The happy-path AsyncPostgresSaver requires a live Postgres (validated separately
against Neon), so here we cover the DSN conversion, the graceful fallback to a
MemorySaver singleton when Postgres is unreachable, and the cached-saver path.
"""
from __future__ import annotations

import pytest

import app.core.checkpointer as cp


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Each test starts and ends with the module singletons cleared."""
    cp._pg_saver = None
    cp._pg_pool = None
    cp._memory_saver = None
    yield
    cp._pg_saver = None
    cp._pg_pool = None
    cp._memory_saver = None


def test_psycopg_dsn_strips_asyncpg_driver_keeps_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cp.settings,
        "database_url",
        "postgresql+asyncpg://u:p@host.neon.tech/db?sslmode=require",
    )
    dsn = cp._psycopg_dsn()
    assert dsn == "postgresql://u:p@host.neon.tech/db?sslmode=require"
    assert "+asyncpg" not in dsn
    assert "sslmode=require" in dsn  # psycopg needs SSL kept for Neon


async def test_falls_back_to_memory_saver_when_pool_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg_pool

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("cannot reach postgres")

    monkeypatch.setattr(psycopg_pool, "AsyncConnectionPool", _boom)

    saver = await cp.get_checkpointer()

    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(saver, MemorySaver)
    # Subsequent calls return the very same MemorySaver instance (singleton).
    assert await cp.get_checkpointer() is saver
    # Falling back must not leave a Postgres saver/pool around.
    assert cp._pg_saver is None
    assert cp._pg_pool is None


async def test_returns_cached_postgres_saver_without_reconnecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    cp._pg_saver = sentinel

    # If it tried to build a pool we'd know — make that path explode.
    import psycopg_pool

    def _should_not_run(*_a: object, **_k: object) -> object:
        raise AssertionError("must not rebuild when a saver is cached")

    monkeypatch.setattr(psycopg_pool, "AsyncConnectionPool", _should_not_run)

    assert await cp.get_checkpointer() is sentinel
