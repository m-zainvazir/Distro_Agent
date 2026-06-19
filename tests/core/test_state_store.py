"""StateStore — Redis path (faked) + in-memory fallback, and campaign_service wiring."""
from __future__ import annotations

import json
from typing import Any

import pytest

import app.core.state_store as ss
import app.services.campaign_service as cs


class _FakeRedis:
    """Minimal in-memory stand-in for the redis client surface StateStore uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def scan_iter(self, match: str = "*") -> Any:
        prefix = match.rstrip("*")
        return iter([k for k in self.store if k.startswith(prefix)])


# ---------------------------------------------------------------------------
# In-memory fallback (Redis unavailable)
# ---------------------------------------------------------------------------


def test_memory_fallback_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ss, "_client_or_none", lambda: None)
    store = ss.StateStore("test:ns")

    assert store.get("a") is None
    store.set("a", {"v": 1})
    store.set("b", {"v": 2})
    assert store.get("a") == {"v": 1}
    assert set(store.keys()) == {"a", "b"}

    store.delete("a")
    assert store.get("a") is None
    assert store.keys() == ["b"]


# ---------------------------------------------------------------------------
# Redis path (faked client)
# ---------------------------------------------------------------------------


def test_redis_path_uses_namespaced_keys_and_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(ss, "_client_or_none", lambda: fake)
    store = ss.StateStore("test:ns", default_ttl=60)

    store.set("k1", {"hello": "world"})
    # Value is JSON-serialised under the namespaced key with the default TTL.
    assert fake.store["test:ns:k1"] == json.dumps({"hello": "world"})
    assert fake.set_calls[0] == ("test:ns:k1", json.dumps({"hello": "world"}), 60)

    assert store.get("k1") == {"hello": "world"}
    assert store.keys() == ["k1"]

    store.delete("k1")
    assert store.get("k1") is None


def test_set_ttl_override(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(ss, "_client_or_none", lambda: fake)
    store = ss.StateStore("test:ns", default_ttl=60)

    store.set("k", {"x": 1}, ttl=5)
    assert fake.set_calls[0][2] == 5


def test_redis_error_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def set(self, *_a: Any, **_k: Any) -> None:
            raise RuntimeError("redis down")

        def get(self, *_a: Any, **_k: Any) -> None:
            raise RuntimeError("redis down")

    monkeypatch.setattr(ss, "_client_or_none", lambda: _Boom())
    store = ss.StateStore("test:ns")

    # set swallows the redis error and writes to the in-process dict instead.
    store.set("k", {"v": 9})
    assert store.get("k") == {"v": 9}


def test_client_disabled_after_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    ss._reset_for_tests()
    attempts = {"n": 0}

    class _FakeRedisModule:
        @staticmethod
        def from_url(*_a: Any, **_k: Any) -> Any:
            attempts["n"] += 1

            class _C:
                def ping(self) -> None:
                    raise ConnectionError("refused")

            return _C()

    monkeypatch.setitem(__import__("sys").modules, "redis", _FakeRedisModule)
    assert ss._client_or_none() is None
    # Second call must not retry the connection (disabled for the process).
    assert ss._client_or_none() is None
    assert attempts["n"] == 1
    ss._reset_for_tests()


# ---------------------------------------------------------------------------
# campaign_service wiring
# ---------------------------------------------------------------------------


def test_campaign_service_register_get_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ss, "_client_or_none", lambda: None)
    # Fresh store so this test is isolated from any process-wide state.
    monkeypatch.setattr(cs, "_store", ss.StateStore("campaign:approval:test"))

    cs.register_pending_approval(
        email_id="e1",
        thread_id="phase2-c1-s1",
        store_name="Indie Boutique",
        graph_type="phase2",
        tenant_id="t1",
    )

    rec = cs.get_pending_approval("e1")
    assert rec == {
        "thread_id": "phase2-c1-s1",
        "store_name": "Indie Boutique",
        "graph_type": "phase2",
        "tenant_id": "t1",
    }
    assert cs.list_pending_approval_ids() == ["e1"]

    cs.remove_pending_approval("e1")
    assert cs.get_pending_approval("e1") is None
    assert cs.list_pending_approval_ids() == []
