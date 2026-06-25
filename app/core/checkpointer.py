"""Checkpointer factory for LangGraph HITL graphs.

Production: AsyncPostgresSaver backed by a long-lived psycopg connection pool —
            state survives process restarts and supports horizontal scaling, so
            a graph paused at a HITL interrupt can be resumed by a later request
            (or a different worker) after the WhatsApp approval tap arrives.
Dev/test:   MemorySaver — in-process only, no external dependency required.

Callers should use ``get_checkpointer()`` rather than importing either class
directly, so the fallback is transparent. The returned saver is a process-wide
singleton; the pool is opened and ``setup()`` (table creation) is run exactly
once, guarded by a lock against concurrent first-callers.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.core.logging import logger

# Process-wide singletons so all graph invocations/resumes share one state store.
_pg_saver: Any = None
_pg_pool: Any = None
_memory_saver: Any = None
_init_lock = asyncio.Lock()


def _psycopg_dsn() -> str:
    """Convert the app's SQLAlchemy/asyncpg DSN into a psycopg-compatible one.

    asyncpg uses the ``postgresql+asyncpg://`` prefix; psycopg wants plain
    ``postgresql://``. Unlike asyncpg, psycopg accepts ``sslmode=require`` in the
    URL, so we keep the query string as-is (Neon requires SSL).
    """
    return (
        settings.database_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )


async def get_checkpointer() -> Any:
    """Return a Postgres-backed saver if reachable, else a MemorySaver singleton."""
    global _pg_saver, _pg_pool, _memory_saver

    if _pg_saver is not None:
        return _pg_saver

    async with _init_lock:
        # Re-check after acquiring the lock — another coroutine may have built it.
        if _pg_saver is not None:
            return _pg_saver

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            # autocommit + prepare_threshold=0 are the langgraph-documented
            # settings; prepare_threshold=0 also keeps us compatible with the
            # Neon connection pooler (PgBouncer). dict_row is what
            # AsyncPostgresSaver expects from its connections.
            pool = AsyncConnectionPool(
                conninfo=_psycopg_dsn(),
                min_size=1,
                max_size=5,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            await pool.open(wait=True, timeout=10.0)

            # mypy can't infer the dict_row factory from the kwargs dict, so the
            # pool is typed as tuple-row; the row_factory above satisfies the
            # saver's real requirement (validated against Neon).
            saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
            await saver.setup()  # idempotent: creates checkpoint tables if absent

            _pg_pool = pool
            _pg_saver = saver
            logger.info("checkpointer_postgres_selected")
            return _pg_saver
        except Exception as exc:
            logger.warning(
                "checkpointer_fallback_to_memory",
                reason=str(exc)[:160],
                fallback="MemorySaver",
            )
            from langgraph.checkpoint.memory import MemorySaver

            if _memory_saver is None:
                _memory_saver = MemorySaver()
            return _memory_saver
