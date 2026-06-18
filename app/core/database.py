import re
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
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
