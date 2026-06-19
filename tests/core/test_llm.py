"""Multi-provider LLM failover (app/core/llm.py)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import app.core.llm as llm


class RateLimitError(Exception):
    """Name matches llm._RETRYABLE_NAMES → treated as retryable."""


class BadRequestError(Exception):
    """Not retryable (name unknown, no status_code)."""


def _client_factory(by_key: dict[str, tuple[str, Any]]) -> Any:
    """Build a fake AsyncGroq class. by_key maps api_key → ("ok", content) | ("raise", exc)."""
    captured: dict[str, list] = {"keys": [], "models": []}

    def make(api_key: str) -> MagicMock:
        captured["keys"].append(api_key)
        client = MagicMock()

        async def create(model: str, messages: list, **kw: Any) -> MagicMock:
            captured["models"].append(model)
            action = by_key[api_key]
            if action[0] == "raise":
                raise action[1]
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = action[1]
            return resp

        client.chat.completions.create = create
        return client

    make.captured = captured  # type: ignore[attr-defined]
    return make


def _set(monkeypatch: pytest.MonkeyPatch, *, primary_key: str, fb_key: str, fb_model: str) -> None:
    monkeypatch.setattr(llm.settings, "groq_api_key", primary_key)
    monkeypatch.setattr(llm.settings, "groq_api_key_fallback", fb_key)
    monkeypatch.setattr(llm.settings, "groq_model_fallback", fb_model)


_MSGS = [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_primary_success_single_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, primary_key="primary", fb_key="", fb_model="")
    make = _client_factory({"primary": ("ok", "hello")})

    resp = await llm.groq_chat(make, messages=_MSGS, model="m1")

    assert resp.choices[0].message.content == "hello"
    assert make.captured["keys"] == ["primary"]  # fallback never instantiated
    assert make.captured["models"] == ["m1"]


@pytest.mark.asyncio
async def test_failover_on_retryable_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, primary_key="primary", fb_key="fallback", fb_model="m2")
    make = _client_factory(
        {"primary": ("raise", RateLimitError("429")), "fallback": ("ok", "recovered")}
    )

    resp = await llm.groq_chat(make, messages=_MSGS, model="m1")

    assert resp.choices[0].message.content == "recovered"
    assert make.captured["keys"] == ["primary", "fallback"]
    assert make.captured["models"] == ["m1", "m2"]  # fallback uses its own model


@pytest.mark.asyncio
async def test_status_code_5xx_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, primary_key="primary", fb_key="fallback", fb_model="")
    err = Exception("server error")
    err.status_code = 503  # type: ignore[attr-defined]
    make = _client_factory({"primary": ("raise", err), "fallback": ("ok", "ok")})

    resp = await llm.groq_chat(make, messages=_MSGS, model="m1")

    assert resp.choices[0].message.content == "ok"
    # Fallback with no fallback-model configured reuses the primary model.
    assert make.captured["models"] == ["m1", "m1"]


@pytest.mark.asyncio
async def test_non_retryable_raises_without_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, primary_key="primary", fb_key="fallback", fb_model="m2")
    make = _client_factory({"primary": ("raise", BadRequestError("400"))})

    with pytest.raises(BadRequestError):
        await llm.groq_chat(make, messages=_MSGS, model="m1")

    assert make.captured["keys"] == ["primary"]  # fallback not attempted


@pytest.mark.asyncio
async def test_single_provider_propagates_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, primary_key="primary", fb_key="", fb_model="")
    make = _client_factory({"primary": ("raise", RateLimitError("boom"))})

    with pytest.raises(RateLimitError):
        await llm.groq_chat(make, messages=_MSGS, model="m1")


@pytest.mark.asyncio
async def test_all_providers_fail_raises_last(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, primary_key="primary", fb_key="fallback", fb_model="m2")
    make = _client_factory(
        {
            "primary": ("raise", RateLimitError("first")),
            "fallback": ("raise", RateLimitError("second")),
        }
    )

    with pytest.raises(RateLimitError, match="second"):
        await llm.groq_chat(make, messages=_MSGS, model="m1")

    assert make.captured["keys"] == ["primary", "fallback"]
