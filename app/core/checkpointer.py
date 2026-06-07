"""Checkpointer factory for LangGraph HITL graphs.

Production: AsyncPostgresSaver — state survives process restarts and supports
            horizontal scaling.
Dev/test:   MemorySaver — in-process only, no external dependency required.

Callers should use ``get_checkpointer()`` rather than importing either class
directly, so the fallback is transparent.
"""

from typing import Any

from app.core.logging import logger


def get_checkpointer() -> Any:
    """Return the best available LangGraph checkpointer for this environment.

    Tries ``AsyncPostgresSaver`` first (requires ``libpq`` + psycopg).
    Falls back to ``MemorySaver`` when libpq is not installed (local dev /
    CI environments that don't run Postgres).
    """
    from app.core.config import settings

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # Convert asyncpg DSN → psycopg DSN (different driver prefix)
        dsn = settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        ).replace(
            "postgres+asyncpg://", "postgresql://"
        )
        checkpointer = AsyncPostgresSaver.from_conn_string(dsn)
        logger.info("checkpointer_postgres_selected")
        return checkpointer
    except Exception as exc:
        logger.warning(
            "checkpointer_postgres_unavailable",
            reason=str(exc)[:120],
            fallback="MemorySaver",
        )
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
