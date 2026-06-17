from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base and all models so Alembic discovers every table
from app.models.base import Base
import app.models.campaign       # noqa: F401
import app.models.user           # noqa: F401
import app.models.sending_domain # noqa: F401

import os

target_metadata = Base.metadata

# Build the DB URL from raw env vars so Railway's injected PG* variables
# take precedence over anything in the .env file (which is copied into Docker).
def _resolve_db_url() -> str:
    """Return a psycopg (v3) synchronous URL for alembic.

    Uses raw os.environ so Railway-injected vars are always preferred over
    anything baked into the Docker image via the .env file.
    """
    url = os.environ.get("DATABASE_URL", "")
    is_railway = "rlwy.net" in url or (
        "railway" in url and "localhost" not in url and "127.0.0.1" not in url
    )

    if is_railway:
        # Strip asyncpg dialect; use psycopg (v3) which handles sslmode natively.
        base = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}sslmode=require"

    # Internal Railway (postgres.railway.internal) — no SSL needed.
    if url and "localhost" not in url and "127.0.0.1" not in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)

    host = os.environ.get("PGHOST", "")
    if host:
        user = os.environ.get("PGUSER", "postgres")
        password = os.environ.get("PGPASSWORD", "")
        port = os.environ.get("PGPORT", "5432")
        db = os.environ.get("PGDATABASE", "railway")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    return "postgresql://postgres:postgres@localhost:5432/distroagent"

config.set_main_option("sqlalchemy.url", _resolve_db_url())

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations synchronously via psycopg (v3).

    Uses a synchronous engine so sslmode=require in the URL is handled by
    libpq — avoiding asyncpg's SSL negotiation issue with Railway's proxy.
    """
    from sqlalchemy import create_engine as _create_engine

    connectable = _create_engine(
        _resolve_db_url(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)  # type: ignore[arg-type]


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
