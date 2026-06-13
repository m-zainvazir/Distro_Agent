"""Checkpointer factory for LangGraph HITL graphs.

Production: AsyncPostgresSaver — state survives process restarts and supports
            horizontal scaling.
Dev/test:   MemorySaver — in-process only, no external dependency required.

Callers should use ``get_checkpointer()`` rather than importing either class
directly, so the fallback is transparent.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import logger

# Singleton so all graph invocations and resumes share the same state store.
_memory_saver: Any = None


async def get_checkpointer() -> Any:
    """Return an AsyncPostgresSaver if libpq is available, else MemorySaver."""
    global _memory_saver
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import]

        dsn = (
            settings.database_url
            .replace("postgresql+asyncpg://", "postgresql://")
            .replace("postgres+asyncpg://", "postgresql://")
        )
        checkpointer = AsyncPostgresSaver.from_conn_string(dsn)
        # Newer langgraph versions return a context manager — unusable as a direct saver
        if hasattr(checkpointer, "__aenter__"):
            raise RuntimeError("AsyncPostgresSaver.from_conn_string returned a context manager")
        logger.info("checkpointer_postgres_selected")
        return checkpointer
    except Exception as exc:
        logger.warning(
            "checkpointer_fallback_to_memory",
            reason=str(exc)[:120],
            fallback="MemorySaver",
        )
        from langgraph.checkpoint.memory import MemorySaver

        if _memory_saver is None:
            _memory_saver = MemorySaver()
        return _memory_saver
