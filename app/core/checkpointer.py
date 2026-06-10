"""Checkpointer factory — tries AsyncPostgresSaver, falls back to MemorySaver."""
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

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        return AsyncPostgresSaver.from_conn_string(dsn)
    except Exception as exc:
        logger.warning("checkpointer_fallback_to_memory", error=str(exc))
        from langgraph.checkpoint.memory import MemorySaver

        if _memory_saver is None:
            _memory_saver = MemorySaver()
        return _memory_saver
