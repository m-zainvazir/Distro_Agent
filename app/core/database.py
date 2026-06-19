import asyncio
import re
import time
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import logger
from app.models.base import Base  # noqa: F401 — single source of truth for all models


def _engine_params(raw_url: str) -> tuple[str, dict]:
    """Return (url, connect_args) suitable for asyncpg.

    asyncpg doesn't accept 'sslmode' as a connection kwarg — it uses ssl=True.
    Strip sslmode from the URL and promote it to connect_args instead.
    """
    connect_args: dict = {}
    url = raw_url
    if "sslmode=" in url:
        mode = re.search(r"sslmode=([^&]+)", url)
        if mode and mode.group(1) in ("require", "verify-ca", "verify-full"):
            connect_args["ssl"] = True
        url = re.sub(r"[?&]sslmode=[^&]*", "", url)
        url = url.rstrip("?").rstrip("&")
    return url, connect_args


_db_url, _connect_args = _engine_params(settings.database_url)
engine = create_async_engine(
    _db_url,
    echo=False,
    connect_args=_connect_args,
    pool_pre_ping=True,   # discard stale connections before use
    pool_recycle=300,     # recycle connections every 5 min (before Neon idle timeout)
    pool_size=5,
    max_overflow=10,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def check_db(max_attempts: int = 3, base_delay: float = 0.5) -> dict:
    """Run `SELECT 1` with retries, returning a health summary.

    Neon's free tier suspends compute after ~5 min idle; the first connection
    after a suspend can fail (connection refused/closed) for the ~1-3s the
    compute takes to wake. Retrying with linear backoff lets a health probe wake
    the database rather than report it down.

    Returns ``{"ok", "attempts", "latency_ms", "error"}``.
    """
    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        start = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            return {
                "ok": True,
                "attempts": attempt,
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
                "error": None,
            }
        except Exception as exc:
            last_error = str(exc)[:200]
            logger.warning("db_health_attempt_failed", attempt=attempt, error=last_error)
            if attempt < max_attempts:
                await asyncio.sleep(base_delay * attempt)

    return {
        "ok": False,
        "attempts": max_attempts,
        "latency_ms": None,
        "error": last_error,
    }
