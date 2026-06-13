"""Tests for app/core/governance.py and app/api/v1/governance.py.

All Redis, httpx, and WhatsApp calls are mocked.
"""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.governance import (
    extract_token_id,
    generate_approval_token,
    publish_approval_decision,
    require_admin_approval,
    send_approval_request,
    store_token_metadata,
    verify_token,
    wait_for_approval,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTION = "update_scoring_weights"
_PAYLOAD: dict[str, Any] = {"vertical": "footwear", "old": 0.35, "new": 0.40}


def _build_token(
    action_type: str = _ACTION,
    payload: dict[str, Any] | None = None,
) -> str:
    """Generate a fresh signed token."""
    return generate_approval_token(action_type, payload or _PAYLOAD)


def _token_metadata(token: str, action_type: str = _ACTION) -> str:
    """Produce the JSON string that Redis would return for this token."""
    return json.dumps(
        {"action_type": action_type, "payload": _PAYLOAD, "token": token},
        default=str,
    )


def _mock_redis_get(return_value: str | None) -> MagicMock:
    """Return a Redis client mock whose .get() returns return_value."""
    r = MagicMock()
    r.get.return_value = return_value
    r.close = MagicMock()
    return r


# ---------------------------------------------------------------------------
# generate_approval_token
# ---------------------------------------------------------------------------


class TestGenerateApprovalToken:
    def test_has_three_parts(self) -> None:
        token = _build_token()
        assert token.count(":") >= 2

    def test_unique_per_call(self) -> None:
        t1 = _build_token()
        t2 = _build_token()
        assert extract_token_id(t1) != extract_token_id(t2)

    def test_extract_token_id_returns_prefix(self) -> None:
        token = _build_token()
        tid = extract_token_id(token)
        assert token.startswith(tid)
        assert len(tid) == 32  # UUID4 hex

    def test_token_contains_timestamp(self) -> None:
        before = int(time.time())
        token = _build_token()
        after = int(time.time())
        parts = token.split(":", 2)
        ts = int(parts[1])
        assert before <= ts <= after + 1


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    def test_valid_token_returns_true(self) -> None:
        token = _build_token()
        meta = _token_metadata(token)

        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(meta)):
            assert verify_token(token, _ACTION) is True

    def test_wrong_action_type_returns_false(self) -> None:
        token = _build_token()
        meta = _token_metadata(token, action_type=_ACTION)

        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(meta)):
            assert verify_token(token, "different_action") is False

    def test_missing_redis_entry_returns_false(self) -> None:
        token = _build_token()
        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(None)):
            assert verify_token(token, _ACTION) is False

    def test_tampered_signature_returns_false(self) -> None:
        token = _build_token()
        parts = token.split(":", 2)
        tampered = ":".join([parts[0], parts[1], "deadbeef" * 8])
        meta = _token_metadata(tampered)

        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(meta)):
            assert verify_token(tampered, _ACTION) is False

    def test_malformed_json_returns_false(self) -> None:
        token = _build_token()
        with patch("app.core.governance._redis_client", return_value=_mock_redis_get("not-json")):
            assert verify_token(token, _ACTION) is False

    def test_token_with_wrong_payload_returns_false(self) -> None:
        token = _build_token()
        # Store metadata with a different payload than what was signed
        corrupted = json.dumps(
            {"action_type": _ACTION, "payload": {"tampered": True}, "token": token},
            default=str,
        )
        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(corrupted)):
            assert verify_token(token, _ACTION) is False


# ---------------------------------------------------------------------------
# publish_approval_decision
# ---------------------------------------------------------------------------


class TestPublishApprovalDecision:
    def test_publishes_approved(self) -> None:
        r = MagicMock()
        r.close = MagicMock()
        with patch("app.core.governance._redis_client", return_value=r):
            publish_approval_decision("abc123", approved=True)
        r.publish.assert_called_once_with("governance:approval:abc123", "approved")

    def test_publishes_rejected(self) -> None:
        r = MagicMock()
        r.close = MagicMock()
        with patch("app.core.governance._redis_client", return_value=r):
            publish_approval_decision("abc123", approved=False)
        r.publish.assert_called_once_with("governance:approval:abc123", "rejected")


# ---------------------------------------------------------------------------
# store_token_metadata
# ---------------------------------------------------------------------------


class TestStoreTokenMetadata:
    def test_stores_with_ttl(self) -> None:
        token = _build_token()
        r = MagicMock()
        r.close = MagicMock()
        with patch("app.core.governance._redis_client", return_value=r):
            store_token_metadata(token, _ACTION, _PAYLOAD)
        r.set.assert_called_once()
        _, kwargs = r.set.call_args
        # ex= (TTL) must be set
        assert kwargs.get("ex") or r.set.call_args[0][2]  # positional or keyword

    def test_key_contains_token_id(self) -> None:
        token = _build_token()
        tid = extract_token_id(token)
        r = MagicMock()
        r.close = MagicMock()
        with patch("app.core.governance._redis_client", return_value=r):
            store_token_metadata(token, _ACTION, _PAYLOAD)
        key_arg = r.set.call_args[0][0]
        assert tid in key_arg


# ---------------------------------------------------------------------------
# send_approval_request
# ---------------------------------------------------------------------------


class TestSendApprovalRequest:
    def test_posts_to_whatsapp_api(self) -> None:
        token = _build_token()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with (
            patch("app.core.governance.settings") as mock_settings,
            patch("app.core.governance.httpx") as mock_httpx,
        ):
            mock_settings.admin_phone = "+15550000001"
            mock_settings.whatsapp_founder_phone = ""
            mock_settings.base_url = "http://localhost:8000"
            mock_settings.whatsapp_phone_number_id = "999"
            mock_settings.whatsapp_access_token = "tok"
            mock_httpx.Client.return_value = mock_client
            send_approval_request(token, _ACTION, _PAYLOAD)

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1]["json"]["text"]["body"]
        assert "approve" in body.lower()
        assert "reject" in body.lower()
        assert _ACTION in body

    def test_skips_when_no_phone_configured(self) -> None:
        token = _build_token()
        with (
            patch("app.core.governance.settings") as mock_settings,
            patch("app.core.governance.httpx") as mock_httpx,
        ):
            mock_settings.admin_phone = ""
            mock_settings.whatsapp_founder_phone = ""
            send_approval_request(token, _ACTION, _PAYLOAD)
        mock_httpx.Client.assert_not_called()

    def test_approve_url_contains_base_url(self) -> None:
        token = _build_token()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with (
            patch("app.core.governance.settings") as mock_settings,
            patch("app.core.governance.httpx") as mock_httpx,
        ):
            mock_settings.admin_phone = "+1555"
            mock_settings.whatsapp_founder_phone = ""
            mock_settings.base_url = "https://distroagent.fly.dev"
            mock_settings.whatsapp_phone_number_id = "1"
            mock_settings.whatsapp_access_token = "t"
            mock_httpx.Client.return_value = mock_client
            send_approval_request(token, _ACTION, _PAYLOAD)

        body = mock_client.post.call_args[1]["json"]["text"]["body"]
        assert "distroagent.fly.dev" in body


# ---------------------------------------------------------------------------
# wait_for_approval
# ---------------------------------------------------------------------------


class TestWaitForApproval:
    def _mock_pubsub(self, message_data: str | None) -> MagicMock:
        """Pubsub that returns one message (or None) then None forever."""
        msgs = (
            [{"type": "message", "data": message_data}] if message_data else [None]
        )

        pubsub = MagicMock()
        pubsub.get_message.side_effect = msgs + [None] * 100
        pubsub.subscribe = MagicMock()
        pubsub.unsubscribe = MagicMock()
        pubsub.close = MagicMock()
        return pubsub

    def _mock_redis(self, pubsub: MagicMock) -> MagicMock:
        r = MagicMock()
        r.pubsub.return_value = pubsub
        r.close = MagicMock()
        return r

    def test_returns_true_on_approved(self) -> None:
        token = _build_token()
        pubsub = self._mock_pubsub("approved")
        r = self._mock_redis(pubsub)
        with patch("app.core.governance._redis_client", return_value=r):
            result = wait_for_approval(token, timeout_seconds=10)
        assert result is True

    def test_returns_false_on_rejected(self) -> None:
        token = _build_token()
        pubsub = self._mock_pubsub("rejected")
        r = self._mock_redis(pubsub)
        with patch("app.core.governance._redis_client", return_value=r):
            result = wait_for_approval(token, timeout_seconds=10)
        assert result is False

    def test_returns_false_on_timeout(self) -> None:
        token = _build_token()
        pubsub = self._mock_pubsub(None)  # no message ever arrives
        r = self._mock_redis(pubsub)
        with patch("app.core.governance._redis_client", return_value=r):
            # timeout_seconds=0 — deadline is immediately past
            result = wait_for_approval(token, timeout_seconds=0)
        assert result is False

    def test_unsubscribes_on_exit(self) -> None:
        token = _build_token()
        pubsub = self._mock_pubsub("approved")
        r = self._mock_redis(pubsub)
        with patch("app.core.governance._redis_client", return_value=r):
            wait_for_approval(token, timeout_seconds=10)
        pubsub.unsubscribe.assert_called_once()


# ---------------------------------------------------------------------------
# require_admin_approval (integration — all I/O mocked)
# ---------------------------------------------------------------------------


class TestRequireAdminApproval:
    def test_returns_true_when_approved(self) -> None:
        with (
            patch("app.core.governance.store_token_metadata"),
            patch("app.core.governance.send_approval_request"),
            patch("app.core.governance.wait_for_approval", return_value=True),
        ):
            result = require_admin_approval(_ACTION, _PAYLOAD)
        assert result is True

    def test_returns_false_when_rejected(self) -> None:
        with (
            patch("app.core.governance.store_token_metadata"),
            patch("app.core.governance.send_approval_request"),
            patch("app.core.governance.wait_for_approval", return_value=False),
        ):
            result = require_admin_approval(_ACTION, _PAYLOAD)
        assert result is False

    def test_calls_store_before_send(self) -> None:
        call_order: list[str] = []

        def fake_store(*args: Any, **kwargs: Any) -> None:
            call_order.append("store")

        def fake_send(*args: Any, **kwargs: Any) -> None:
            call_order.append("send")

        with (
            patch("app.core.governance.store_token_metadata", side_effect=fake_store),
            patch("app.core.governance.send_approval_request", side_effect=fake_send),
            patch("app.core.governance.wait_for_approval", return_value=True),
        ):
            require_admin_approval(_ACTION, _PAYLOAD)

        assert call_order == ["store", "send"]

    def test_wait_receives_same_token_as_store(self) -> None:
        stored_tokens: list[str] = []
        waited_tokens: list[str] = []

        def fake_store(token: str, *args: Any, **kwargs: Any) -> None:
            stored_tokens.append(token)

        def fake_wait(token: str, **kwargs: Any) -> bool:
            waited_tokens.append(token)
            return True

        with (
            patch("app.core.governance.store_token_metadata", side_effect=fake_store),
            patch("app.core.governance.send_approval_request"),
            patch("app.core.governance.wait_for_approval", side_effect=fake_wait),
        ):
            require_admin_approval(_ACTION, _PAYLOAD)

        assert stored_tokens == waited_tokens


# ---------------------------------------------------------------------------
# HTTP endpoints (approve / reject)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


class TestGovernanceEndpoints:
    def test_approve_valid_token(self, client: TestClient) -> None:
        token = _build_token()
        meta = _token_metadata(token)

        # verify_token lives in app.core.governance and calls _redis_client() there.
        # publish_approval_decision was imported by value into the endpoint module.
        with (
            patch("app.core.governance._redis_client", return_value=_mock_redis_get(meta)),
            patch("app.api.v1.governance.publish_approval_decision") as mock_pub,
        ):
            resp = client.get(f"/api/v1/governance/approve?token={token}&action={_ACTION}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        mock_pub.assert_called_once_with(extract_token_id(token), approved=True)

    def test_reject_valid_token(self, client: TestClient) -> None:
        token = _build_token()
        meta = _token_metadata(token)

        with (
            patch("app.core.governance._redis_client", return_value=_mock_redis_get(meta)),
            patch("app.api.v1.governance.publish_approval_decision") as mock_pub,
        ):
            resp = client.get(f"/api/v1/governance/reject?token={token}&action={_ACTION}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        mock_pub.assert_called_once_with(extract_token_id(token), approved=False)

    def test_approve_invalid_token_returns_403(self, client: TestClient) -> None:
        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(None)):
            resp = client.get("/api/v1/governance/approve?token=bad:token:sig&action=foo")
        assert resp.status_code == 403

    def test_reject_invalid_token_returns_403(self, client: TestClient) -> None:
        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(None)):
            resp = client.get("/api/v1/governance/reject?token=bad:token:sig&action=foo")
        assert resp.status_code == 403

    def test_approve_missing_params_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/governance/approve")
        assert resp.status_code == 422

    def test_reject_missing_params_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/governance/reject")
        assert resp.status_code == 422

    def test_tampered_token_returns_403(self, client: TestClient) -> None:
        token = _build_token()
        # Corrupt the signature portion
        parts = token.split(":", 2)
        tampered = ":".join([parts[0], parts[1], "aaaa" * 16])
        meta = _token_metadata(tampered)
        with patch("app.core.governance._redis_client", return_value=_mock_redis_get(meta)):
            resp = client.get(
                f"/api/v1/governance/approve?token={tampered}&action={_ACTION}"
            )
        assert resp.status_code == 403
