"""Redis-backed ephemeral key/value store with an in-memory fallback.

Used for short-lived shared state that must survive a process restart and be
visible across workers — HITL pending approvals and discovery task status.

When Redis is unreachable (local dev, CI, or a Railway free-tier service with no
Redis attached) the store degrades to a per-process dict instead of crashing, so
single-worker setups keep working exactly as before. The connection is probed
once; on failure Redis is disabled for the process lifetime (matching the
checkpointer's one-shot fallback), avoiding repeated connect timeouts.

Values must be JSON-serialisable.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.core.logging import logger

_client: Any = None
_redis_disabled = False


def _client_or_none() -> Any | None:
    """Return a live redis client, or None to signal the in-memory fallback."""
    global _client, _redis_disabled
    if _redis_disabled:
        return None
    if _client is None:
        try:
            import redis  # local import — avoids loading redis at module import time

            client = redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            _client = client
            logger.info("state_store_redis_connected")
        except Exception as exc:
            _redis_disabled = True
            logger.warning("state_store_memory_fallback", reason=str(exc)[:120])
            return None
    return _client


def _reset_for_tests() -> None:
    """Clear the cached connection state (test helper only)."""
    global _client, _redis_disabled
    _client = None
    _redis_disabled = False


class StateStore:
    """Namespaced JSON key/value store: Redis when available, else in-process dict."""

    def __init__(self, namespace: str, default_ttl: int | None = None) -> None:
        self._ns = namespace
        self._ttl = default_ttl
        self._mem: dict[str, dict] = {}

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def set(self, key: str, value: dict, ttl: int | None = None) -> None:
        client = _client_or_none()
        if client is not None:
            try:
                client.set(self._key(key), json.dumps(value), ex=ttl or self._ttl)
                return
            except Exception as exc:
                logger.warning("state_store_set_failed", key=key, error=str(exc)[:120])
        self._mem[key] = value

    def get(self, key: str) -> dict | None:
        client = _client_or_none()
        if client is not None:
            try:
                raw = client.get(self._key(key))
                return json.loads(raw) if raw is not None else None
            except Exception as exc:
                logger.warning("state_store_get_failed", key=key, error=str(exc)[:120])
        return self._mem.get(key)

    def delete(self, key: str) -> None:
        client = _client_or_none()
        if client is not None:
            try:
                client.delete(self._key(key))
                return
            except Exception as exc:
                logger.warning("state_store_delete_failed", key=key, error=str(exc)[:120])
        self._mem.pop(key, None)

    def keys(self) -> list[str]:
        client = _client_or_none()
        if client is not None:
            try:
                prefix = f"{self._ns}:"
                return [k[len(prefix):] for k in client.scan_iter(match=f"{prefix}*")]
            except Exception as exc:
                logger.warning("state_store_keys_failed", error=str(exc)[:120])
        return list(self._mem.keys())
