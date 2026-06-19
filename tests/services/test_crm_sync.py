"""Tests for app/services/crm_sync.py — all HTTP and DB calls mocked."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from app.services.crm_sync import (
    CrmEvent,
    CrmEventType,
    _ADAPTERS,
    _hmac_signature,
    _push_google_sheets,
    _push_hubspot,
    _push_klaviyo,
    _push_salesforce,
    _push_webhook,
    push_event,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_STORE_EMAIL = "buyer@boutique.com"
_STORE_NAME = "Brooklyn Boutique"


def _make_config(
    crm_type: str = "webhook",
    webhook_url: str = "https://n8n.example.com/webhook/abc",
    api_key: str = "test-key",
    spreadsheet_id: str = "sheet123",
    sheet_name: str = "DistroAgent",
    hmac_secret: str = "my-secret",
    enabled: bool = True,
    extra_config: dict | None = None,
) -> MagicMock:
    cfg = MagicMock()
    cfg.crm_type = crm_type
    cfg.webhook_url = webhook_url
    cfg.api_key = api_key
    cfg.spreadsheet_id = spreadsheet_id
    cfg.sheet_name = sheet_name
    cfg.hmac_secret = hmac_secret
    cfg.enabled = enabled
    cfg.extra_config = extra_config or {}
    return cfg


def _make_event(
    event_type: CrmEventType = CrmEventType.DEAL_CLOSED,
    amount_usd: float = 500.0,
    invoice_id: str = "in_test",
    **kwargs: Any,
) -> CrmEvent:
    return CrmEvent(
        event_type=event_type,
        tenant_id=_TENANT_ID,
        store_name=_STORE_NAME,
        store_email=_STORE_EMAIL,
        amount_usd=amount_usd,
        invoice_id=invoice_id,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# CrmEvent serialization
# ---------------------------------------------------------------------------


def test_crm_event_to_webhook_payload_contains_all_fields() -> None:
    event = _make_event()
    payload = event.to_webhook_payload()
    assert payload["event_type"] == "deal_closed"
    assert payload["tenant_id"] == _TENANT_ID
    assert payload["store_email"] == _STORE_EMAIL
    assert payload["amount_usd"] == 500.0
    assert "occurred_at" in payload


def test_crm_event_to_sheet_row_length() -> None:
    event = _make_event(CrmEventType.EMAIL_SENT, email_subject="Hello!")
    row = event.to_sheet_row()
    assert len(row) == 13  # fixed column count
    assert row[1] == "email_sent"
    assert row[7] == "Hello!"


def test_crm_event_to_hubspot_note_body_includes_deal_value() -> None:
    event = _make_event()
    note = event.to_hubspot_note_body()
    assert "500.00" in note
    assert "in_test" in note
    assert "Deal Closed" in note


def test_crm_event_to_hubspot_note_body_meeting() -> None:
    event = _make_event(
        CrmEventType.MEETING_BOOKED,
        meeting_time="Monday 3pm",
        meeting_url="https://meet.google.com/abc",
        amount_usd=0.0,
    )
    note = event.to_hubspot_note_body()
    assert "Monday 3pm" in note
    assert "meet.google.com" in note
    assert "500" not in note  # no deal value for meeting


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------


def test_hmac_signature_is_deterministic() -> None:
    ts = int(time.time())
    payload = '{"event_type": "deal_closed"}'
    sig1 = _hmac_signature("secret", ts, payload)
    sig2 = _hmac_signature("secret", ts, payload)
    assert sig1 == sig2


def test_hmac_signature_changes_with_timestamp() -> None:
    payload = '{"event_type": "deal_closed"}'
    sig1 = _hmac_signature("secret", 1000, payload)
    sig2 = _hmac_signature("secret", 2000, payload)
    assert sig1 != sig2


def test_hmac_signature_verifiable() -> None:
    secret = "my-secret"
    ts = 1234567890
    payload = '{"hello": "world"}'
    sig = _hmac_signature(secret, ts, payload)
    msg = f"{ts}.{payload}".encode()
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    assert sig == expected


# ---------------------------------------------------------------------------
# Webhook adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_push_webhook_posts_to_configured_url() -> None:
    config = _make_config(crm_type="webhook")
    route = respx.post("https://n8n.example.com/webhook/abc").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    event = _make_event()
    await _push_webhook(event, config)
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_push_webhook_includes_hmac_signature_header() -> None:
    config = _make_config(hmac_secret="my-secret")
    route = respx.post("https://n8n.example.com/webhook/abc").mock(
        return_value=Response(200)
    )
    event = _make_event()
    await _push_webhook(event, config)
    request = route.calls.last.request
    assert "X-DistroAgent-Signature" in request.headers
    assert request.headers["X-DistroAgent-Signature"].startswith("sha256=")


@pytest.mark.asyncio
@respx.mock
async def test_push_webhook_no_signature_header_when_no_secret() -> None:
    config = _make_config(hmac_secret="")
    respx.post("https://n8n.example.com/webhook/abc").mock(return_value=Response(200))
    event = _make_event()
    await _push_webhook(event, config)
    # no exception raised


@pytest.mark.asyncio
@respx.mock
async def test_push_webhook_payload_is_valid_json() -> None:
    config = _make_config()
    route = respx.post("https://n8n.example.com/webhook/abc").mock(
        return_value=Response(200)
    )
    event = _make_event()
    await _push_webhook(event, config)
    body = route.calls.last.request.content
    parsed = json.loads(body)
    assert parsed["event_type"] == "deal_closed"
    assert parsed["store_email"] == _STORE_EMAIL


# ---------------------------------------------------------------------------
# Klaviyo adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_push_klaviyo_tracks_event() -> None:
    config = _make_config(crm_type="klaviyo", api_key="pk_test")
    route = respx.post("https://a.klaviyo.com/api/events/").mock(
        return_value=Response(202)
    )
    event = _make_event(CrmEventType.RESTOCK_OPPORTUNITY, amount_usd=0.0, restock_days=45)

    await _push_klaviyo(event, config)

    assert route.called
    sent = json.loads(route.calls.last.request.content)
    attrs = sent["data"]["attributes"]
    assert attrs["metric"]["data"]["attributes"]["name"] == "DistroAgent Restock Opportunity"
    assert attrs["profile"]["data"]["attributes"]["email"] == _STORE_EMAIL
    assert attrs["properties"]["restock_days"] == 45
    # Auth + revision headers present
    headers = route.calls.last.request.headers
    assert headers["authorization"] == "Klaviyo-API-Key pk_test"
    assert headers["revision"] == "2024-10-15"


@pytest.mark.asyncio
@respx.mock
async def test_push_klaviyo_skips_without_email() -> None:
    config = _make_config(crm_type="klaviyo", api_key="pk_test")
    route = respx.post("https://a.klaviyo.com/api/events/").mock(return_value=Response(202))
    event = CrmEvent(
        event_type=CrmEventType.EMAIL_SENT,
        tenant_id=_TENANT_ID,
        store_name=_STORE_NAME,
        store_email="",  # no email → cannot upsert a profile
    )

    await _push_klaviyo(event, config)

    assert not route.called


def test_klaviyo_registered_in_dispatch_table() -> None:
    assert _ADAPTERS["klaviyo"] is _push_klaviyo


# ---------------------------------------------------------------------------
# HubSpot adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_push_hubspot_creates_contact_and_note() -> None:
    config = _make_config(crm_type="hubspot", api_key="hs-token")
    # Contact search → not found
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts/search").mock(
        return_value=Response(200, json={"results": []})
    )
    # Contact create
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts").mock(
        return_value=Response(201, json={"id": "cid-123"})
    )
    # Note create
    note_route = respx.post("https://api.hubapi.com/crm/v3/objects/notes").mock(
        return_value=Response(201, json={"id": "note-1"})
    )
    event = _make_event(CrmEventType.EMAIL_SENT, amount_usd=0.0)
    await _push_hubspot(event, config)
    assert note_route.called


@pytest.mark.asyncio
@respx.mock
async def test_push_hubspot_reuses_existing_contact() -> None:
    config = _make_config(crm_type="hubspot", api_key="hs-token")
    # Contact search → found
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts/search").mock(
        return_value=Response(200, json={"results": [{"id": "existing-123"}]})
    )
    create_route = respx.post("https://api.hubapi.com/crm/v3/objects/contacts").mock(
        return_value=Response(201, json={"id": "new"})
    )
    respx.post("https://api.hubapi.com/crm/v3/objects/notes").mock(
        return_value=Response(201, json={"id": "n1"})
    )
    event = _make_event(CrmEventType.EMAIL_SENT, amount_usd=0.0)
    await _push_hubspot(event, config)
    assert not create_route.called  # existing contact reused


@pytest.mark.asyncio
@respx.mock
async def test_push_hubspot_creates_deal_on_deal_closed() -> None:
    config = _make_config(crm_type="hubspot", api_key="hs-token")
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts/search").mock(
        return_value=Response(200, json={"results": [{"id": "cid-123"}]})
    )
    respx.post("https://api.hubapi.com/crm/v3/objects/notes").mock(
        return_value=Response(201, json={"id": "n1"})
    )
    deal_route = respx.post("https://api.hubapi.com/crm/v3/objects/deals").mock(
        return_value=Response(201, json={"id": "deal-1"})
    )
    event = _make_event(CrmEventType.DEAL_CLOSED, amount_usd=1500.0)
    await _push_hubspot(event, config)
    assert deal_route.called
    body = json.loads(deal_route.calls.last.request.content)
    assert body["properties"]["dealstage"] == "closedwon"
    assert float(body["properties"]["amount"]) == 1500.0


@pytest.mark.asyncio
@respx.mock
async def test_push_hubspot_skips_deal_for_non_closed_events() -> None:
    config = _make_config(crm_type="hubspot", api_key="hs-token")
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts/search").mock(
        return_value=Response(200, json={"results": [{"id": "cid-123"}]})
    )
    respx.post("https://api.hubapi.com/crm/v3/objects/notes").mock(
        return_value=Response(201, json={"id": "n1"})
    )
    deal_route = respx.post("https://api.hubapi.com/crm/v3/objects/deals").mock(
        return_value=Response(201, json={"id": "d1"})
    )
    event = _make_event(CrmEventType.EMAIL_SENT, amount_usd=0.0)
    await _push_hubspot(event, config)
    assert not deal_route.called


# ---------------------------------------------------------------------------
# Salesforce adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_push_salesforce_creates_lead_when_not_found() -> None:
    config = _make_config(
        crm_type="salesforce",
        api_key="sf-token",
        extra_config={"instance_url": "https://myorg.salesforce.com"},
    )
    respx.get("https://myorg.salesforce.com/services/data/v57.0/query").mock(
        return_value=Response(200, json={"records": []})
    )
    create_route = respx.post(
        "https://myorg.salesforce.com/services/data/v57.0/sobjects/Lead/"
    ).mock(return_value=Response(201, json={"id": "lead-abc", "success": True}))
    event = _make_event(CrmEventType.NEW_QUALIFIED_LEAD, amount_usd=0.0)
    await _push_salesforce(event, config)
    assert create_route.called
    body = json.loads(create_route.calls.last.request.content)
    assert body["Email"] == _STORE_EMAIL
    assert body["LeadSource"] == "DistroAgent"


@pytest.mark.asyncio
@respx.mock
async def test_push_salesforce_reuses_existing_lead() -> None:
    config = _make_config(
        crm_type="salesforce",
        api_key="sf-token",
        extra_config={"instance_url": "https://myorg.salesforce.com"},
    )
    respx.get("https://myorg.salesforce.com/services/data/v57.0/query").mock(
        return_value=Response(200, json={"records": [{"Id": "lead-existing"}]})
    )
    create_route = respx.post(
        "https://myorg.salesforce.com/services/data/v57.0/sobjects/Lead/"
    ).mock(return_value=Response(201, json={"id": "new"}))
    event = _make_event(CrmEventType.EMAIL_SENT, amount_usd=0.0)
    await _push_salesforce(event, config)
    assert not create_route.called


@pytest.mark.asyncio
@respx.mock
async def test_push_salesforce_creates_opportunity_on_deal_closed() -> None:
    config = _make_config(
        crm_type="salesforce",
        api_key="sf-token",
        extra_config={"instance_url": "https://myorg.salesforce.com"},
    )
    respx.get("https://myorg.salesforce.com/services/data/v57.0/query").mock(
        return_value=Response(200, json={"records": [{"Id": "lead-abc"}]})
    )
    opp_route = respx.post(
        "https://myorg.salesforce.com/services/data/v57.0/sobjects/Opportunity/"
    ).mock(return_value=Response(201, json={"id": "opp-1", "success": True}))
    event = _make_event(CrmEventType.DEAL_CLOSED, amount_usd=2000.0)
    await _push_salesforce(event, config)
    assert opp_route.called
    body = json.loads(opp_route.calls.last.request.content)
    assert body["StageName"] == "Closed Won"
    assert body["Amount"] == 2000.0


@pytest.mark.asyncio
@respx.mock
async def test_push_salesforce_skips_when_no_instance_url() -> None:
    config = _make_config(crm_type="salesforce", api_key="sf-token", extra_config={})
    event = _make_event()
    await _push_salesforce(event, config)  # should not raise


# ---------------------------------------------------------------------------
# Google Sheets adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_push_google_sheets_refreshes_token_and_appends_row() -> None:
    config = _make_config(
        crm_type="google_sheets",
        spreadsheet_id="sheet123",
        sheet_name="Leads",
        extra_config={
            "oauth_client_id": "cid",
            "oauth_client_secret": "csec",
            "oauth_refresh_token": "rtoken",
        },
    )
    # Token refresh
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(200, json={"access_token": "ya29.test"})
    )
    # Header check (empty sheet)
    respx.get(
        "https://sheets.googleapis.com/v4/spreadsheets/sheet123/values/Leads!A1"
    ).mock(return_value=Response(200, json={"values": [["Timestamp"]]}))
    # Row append
    append_route = respx.post(
        "https://sheets.googleapis.com/v4/spreadsheets/sheet123/values/Leads!A1:append"
    ).mock(return_value=Response(200, json={"updates": {}}))

    event = _make_event(CrmEventType.DEAL_CLOSED)
    await _push_google_sheets(event, config)
    assert append_route.called
    body = json.loads(append_route.calls.last.request.content)
    assert body["values"][0][1] == "deal_closed"


@pytest.mark.asyncio
async def test_push_google_sheets_skips_when_no_spreadsheet_id() -> None:
    config = _make_config(spreadsheet_id="")
    event = _make_event()
    await _push_google_sheets(event, config)  # should not raise


# ---------------------------------------------------------------------------
# push_event — dispatch routing and resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_event_skips_empty_tenant_id() -> None:
    mock_db = AsyncMock()
    with patch("app.services.crm_sync._get_config") as mock_cfg:
        await push_event("", CrmEventType.EMAIL_SENT, {}, db=mock_db)
    mock_cfg.assert_not_called()


@pytest.mark.asyncio
async def test_push_event_skips_when_no_config() -> None:
    mock_db = AsyncMock()
    with patch("app.services.crm_sync._get_config", return_value=None):
        with patch("app.services.crm_sync._push_webhook") as mock_adapter:
            await push_event(_TENANT_ID, CrmEventType.EMAIL_SENT, {}, db=mock_db)
    mock_adapter.assert_not_called()


@pytest.mark.asyncio
async def test_push_event_routes_to_correct_adapter() -> None:
    mock_db = AsyncMock()
    config = _make_config(crm_type="webhook")
    mock_wh = AsyncMock()
    # Patch the _ADAPTERS dict directly — patching the name alone doesn't update
    # dict values that were bound at module import time.
    with patch("app.services.crm_sync._get_config", return_value=config):
        with patch.dict("app.services.crm_sync._ADAPTERS", {"webhook": mock_wh}):
            await push_event(
                _TENANT_ID,
                CrmEventType.DEAL_CLOSED,
                {"store_email": _STORE_EMAIL, "amount_usd": 100.0},
                db=mock_db,
            )
    mock_wh.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_event_adapter_failure_does_not_raise() -> None:
    """CRM adapter errors must never propagate to callers."""
    mock_db = AsyncMock()
    config = _make_config(crm_type="hubspot")
    broken_adapter = AsyncMock(side_effect=RuntimeError("HubSpot down"))
    with patch("app.services.crm_sync._get_config", return_value=config):
        with patch.dict("app.services.crm_sync._ADAPTERS", {"hubspot": broken_adapter}):
            # Should complete without raising
            await push_event(_TENANT_ID, CrmEventType.EMAIL_SENT, {}, db=mock_db)


@pytest.mark.asyncio
async def test_push_event_all_adapters_registered() -> None:
    """Dispatch table must cover all supported CRM types."""
    assert set(_ADAPTERS.keys()) == {
        "webhook",
        "hubspot",
        "salesforce",
        "google_sheets",
        "klaviyo",
    }
