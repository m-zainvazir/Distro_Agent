"""CRM sync — push standardized events to each tenant's configured CRM endpoint.

Supports four integration types (configurable per tenant via TenantCrmConfig):
  webhook       — HMAC-signed POST to any URL (n8n, Zapier, Make, custom)
  hubspot       — HubSpot CRM v3 API  (Private App Bearer token)
  salesforce    — Salesforce REST API  (OAuth2 access token + instance URL)
  google_sheets — Google Sheets API v4 (OAuth2 refresh token per tenant)

Entry point:
    await push_event(tenant_id, CrmEventType.DEAL_CLOSED, data)

Critical rule: push_event NEVER raises — CRM failures must not disrupt main flows.
All adapter errors are logged and swallowed.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.logging import logger

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0   # seconds, doubles each attempt
_HTTP_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Event taxonomy
# ---------------------------------------------------------------------------


class CrmEventType(str, Enum):
    NEW_QUALIFIED_LEAD = "new_qualified_lead"
    EMAIL_SENT = "email_sent"
    POSITIVE_REPLY = "positive_reply_received"
    MEETING_BOOKED = "meeting_booked"
    DEAL_CLOSED = "deal_closed"
    RESTOCK_OPPORTUNITY = "restock_opportunity"


# ---------------------------------------------------------------------------
# Standardized event payload
# ---------------------------------------------------------------------------


class CrmEvent(BaseModel):
    """Canonical shape shared across all four adapter types."""

    model_config = ConfigDict(populate_by_name=True)

    event_type: CrmEventType
    tenant_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Store / lead identity
    store_name: str = ""
    store_email: str = ""
    store_address: str = ""
    lead_score: float | None = None

    # Outreach email context
    email_id: str = ""
    email_subject: str = ""

    # Reply / negotiation context
    reply_intent: str = ""

    # Meeting context
    meeting_time: str = ""
    meeting_url: str = ""

    # Deal context
    invoice_id: str = ""
    amount_usd: float = 0.0

    # Restock context
    restock_days: int = 0

    def to_webhook_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_sheet_row(self) -> list[str]:
        """Flat list for Google Sheets row — order matches the header row."""
        return [
            self.occurred_at.isoformat(),
            self.event_type.value,
            self.store_name,
            self.store_email,
            self.store_address,
            str(self.lead_score) if self.lead_score is not None else "",
            self.email_id,
            self.email_subject,
            self.reply_intent,
            self.meeting_time,
            self.meeting_url,
            self.invoice_id,
            f"{self.amount_usd:.2f}" if self.amount_usd else "",
        ]

    def to_hubspot_note_body(self) -> str:
        lines = [f"[DistroAgent] {self.event_type.value.replace('_', ' ').title()}"]
        if self.email_subject:
            lines.append(f"Email: {self.email_subject}")
        if self.reply_intent:
            lines.append(f"Intent: {self.reply_intent}")
        if self.meeting_time:
            lines.append(f"Meeting: {self.meeting_time}")
        if self.meeting_url:
            lines.append(f"Join: {self.meeting_url}")
        if self.amount_usd:
            lines.append(f"Deal value: ${self.amount_usd:,.2f}  |  Invoice: {self.invoice_id}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


async def _get_config(tenant_id: str, db: AsyncSession) -> Any | None:
    """Fetch TenantCrmConfig for this tenant, or None if unconfigured/disabled."""
    from app.models.crm_config import TenantCrmConfig

    try:
        result = await db.execute(
            select(TenantCrmConfig).where(
                TenantCrmConfig.tenant_id == uuid.UUID(tenant_id),
                TenantCrmConfig.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("crm_sync_config_load_failed", tenant_id=tenant_id, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# HTTP helper — POST with retry/backoff on 5xx
# ---------------------------------------------------------------------------


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    content: str | bytes | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    last_exc: Exception | None = None
    response: httpx.Response | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if content is not None:
                response = await client.post(url, content=content, headers=headers)
            else:
                response = await client.post(url, json=json_body, headers=headers)
            if response.status_code < 500:
                return response
            logger.warning(
                "crm_http_5xx",
                url=url,
                attempt=attempt,
                status_code=response.status_code,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning("crm_http_transport_error", url=url, attempt=attempt, error=str(exc))
        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
    if last_exc:
        raise last_exc
    return response  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Adapter — Generic webhook (n8n / Zapier / Make / custom)
# ---------------------------------------------------------------------------


def _hmac_signature(secret: str, timestamp: int, payload_json: str) -> str:
    """HMAC-SHA256 of '{timestamp}.{payload_json}' — same pattern as Stripe."""
    msg = f"{timestamp}.{payload_json}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


async def _push_webhook(event: CrmEvent, config: Any) -> None:
    payload_json = json.dumps(event.to_webhook_payload(), default=str)
    timestamp = int(time.time())

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-DistroAgent-Event": event.event_type.value,
        "X-DistroAgent-Timestamp": str(timestamp),
        "User-Agent": "DistroAgent/1.0",
    }
    if config.hmac_secret:
        sig = _hmac_signature(config.hmac_secret, timestamp, payload_json)
        headers["X-DistroAgent-Signature"] = f"sha256={sig}"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await _post_with_retry(
            client, config.webhook_url, headers=headers, content=payload_json.encode()
        )

    logger.info(
        "crm_webhook_pushed",
        event_type=event.event_type.value,
        status_code=resp.status_code,
        tenant_id=event.tenant_id,
    )


# ---------------------------------------------------------------------------
# Adapter — HubSpot CRM v3
# ---------------------------------------------------------------------------

_HS_BASE = "https://api.hubapi.com"


def _hs_headers(config: Any) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


async def _hs_get_or_create_contact(
    client: httpx.AsyncClient,
    event: CrmEvent,
    config: Any,
) -> str | None:
    """Search for existing HubSpot contact by email; create if not found. Returns contact ID."""
    search_resp = await client.post(
        f"{_HS_BASE}/crm/v3/objects/contacts/search",
        json={
            "filterGroups": [
                {
                    "filters": [
                        {"propertyName": "email", "operator": "EQ", "value": event.store_email}
                    ]
                }
            ],
            "properties": ["email", "company"],
        },
        headers=_hs_headers(config),
    )
    if search_resp.status_code == 200:
        results = search_resp.json().get("results", [])
        if results:
            return str(results[0]["id"])

    # Contact not found — create it
    create_resp = await client.post(
        f"{_HS_BASE}/crm/v3/objects/contacts",
        json={
            "properties": {
                "email": event.store_email,
                "company": event.store_name,
                "lifecyclestage": "lead",
            }
        },
        headers=_hs_headers(config),
    )
    if create_resp.status_code in (200, 201):
        return str(create_resp.json().get("id", ""))
    logger.warning(
        "hubspot_create_contact_failed",
        status_code=create_resp.status_code,
        email=event.store_email,
    )
    return None


async def _hs_create_note(
    client: httpx.AsyncClient,
    event: CrmEvent,
    contact_id: str,
    config: Any,
) -> None:
    ts_ms = int(event.occurred_at.timestamp() * 1000)
    await client.post(
        f"{_HS_BASE}/crm/v3/objects/notes",
        json={
            "properties": {
                "hs_note_body": event.to_hubspot_note_body(),
                "hs_timestamp": str(ts_ms),
            },
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 202,  # note_to_contact
                        }
                    ],
                }
            ],
        },
        headers=_hs_headers(config),
    )


async def _hs_create_deal(
    client: httpx.AsyncClient,
    event: CrmEvent,
    contact_id: str,
    config: Any,
) -> None:
    deal_resp = await client.post(
        f"{_HS_BASE}/crm/v3/objects/deals",
        json={
            "properties": {
                "dealname": f"{event.store_name} — wholesale deal",
                "dealstage": "closedwon",
                "amount": str(event.amount_usd),
                "closedate": event.occurred_at.strftime("%Y-%m-%d"),
            },
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 3,  # deal_to_contact
                        }
                    ],
                }
            ],
        },
        headers=_hs_headers(config),
    )
    if deal_resp.status_code not in (200, 201):
        logger.warning(
            "hubspot_create_deal_failed",
            status_code=deal_resp.status_code,
            store=event.store_name,
        )


async def _push_hubspot(event: CrmEvent, config: Any) -> None:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        contact_id = await _hs_get_or_create_contact(client, event, config)
        if not contact_id:
            return

        await _hs_create_note(client, event, contact_id, config)

        if event.event_type == CrmEventType.DEAL_CLOSED and event.amount_usd:
            await _hs_create_deal(client, event, contact_id, config)

    logger.info(
        "crm_hubspot_pushed",
        event_type=event.event_type.value,
        contact_id=contact_id,
        tenant_id=event.tenant_id,
    )


# ---------------------------------------------------------------------------
# Adapter — Salesforce REST API
# ---------------------------------------------------------------------------


def _sf_instance_url(config: Any) -> str:
    extra = config.extra_config or {}
    return str(extra.get("instance_url", "")).rstrip("/")


def _sf_headers(config: Any) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }


async def _sf_get_or_create_lead(
    client: httpx.AsyncClient,
    event: CrmEvent,
    config: Any,
) -> str | None:
    """Query Lead by Email; create if not found. Returns Salesforce Lead ID."""
    base = _sf_instance_url(config)
    if not base:
        logger.warning("salesforce_missing_instance_url", tenant_id=event.tenant_id)
        return None

    q = f"SELECT Id FROM Lead WHERE Email = '{event.store_email}' LIMIT 1"
    search_resp = await client.get(
        f"{base}/services/data/v57.0/query",
        params={"q": q},
        headers=_sf_headers(config),
    )
    if search_resp.status_code == 200:
        records = search_resp.json().get("records", [])
        if records:
            return str(records[0]["Id"])

    create_resp = await client.post(
        f"{base}/services/data/v57.0/sobjects/Lead/",
        json={
            "Email": event.store_email,
            "Company": event.store_name or "Unknown",
            "LastName": event.store_name or "Lead",
            "Status": "Open - Not Contacted",
            "LeadSource": "DistroAgent",
        },
        headers=_sf_headers(config),
    )
    if create_resp.status_code in (200, 201):
        return str(create_resp.json().get("id", ""))
    logger.warning(
        "salesforce_create_lead_failed",
        status_code=create_resp.status_code,
        email=event.store_email,
    )
    return None


async def _sf_create_opportunity(
    client: httpx.AsyncClient,
    event: CrmEvent,
    lead_id: str,
    config: Any,
) -> None:
    base = _sf_instance_url(config)
    resp = await client.post(
        f"{base}/services/data/v57.0/sobjects/Opportunity/",
        json={
            "Name": f"{event.store_name} — wholesale deal",
            "StageName": "Closed Won",
            "Amount": event.amount_usd,
            "CloseDate": event.occurred_at.strftime("%Y-%m-%d"),
            "LeadSource": "DistroAgent",
            "Description": f"Invoice: {event.invoice_id}",
        },
        headers=_sf_headers(config),
    )
    if resp.status_code not in (200, 201):
        logger.warning(
            "salesforce_create_opportunity_failed",
            status_code=resp.status_code,
            store=event.store_name,
        )


async def _push_salesforce(event: CrmEvent, config: Any) -> None:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        lead_id = await _sf_get_or_create_lead(client, event, config)
        if not lead_id:
            return

        if event.event_type == CrmEventType.DEAL_CLOSED and event.amount_usd:
            await _sf_create_opportunity(client, event, lead_id, config)

    logger.info(
        "crm_salesforce_pushed",
        event_type=event.event_type.value,
        lead_id=lead_id,
        tenant_id=event.tenant_id,
    )


# ---------------------------------------------------------------------------
# Adapter — Google Sheets API v4
# ---------------------------------------------------------------------------

_GSHEETS_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GSHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


async def _gsheets_get_access_token(client: httpx.AsyncClient, config: Any) -> str:
    """Exchange stored OAuth2 refresh token for a short-lived access token."""
    extra = config.extra_config or {}
    resp = await client.post(
        _GSHEETS_TOKEN_URL,
        data={
            "client_id": extra.get("oauth_client_id", ""),
            "client_secret": extra.get("oauth_client_secret", ""),
            "refresh_token": extra.get("oauth_refresh_token", ""),
            "grant_type": "refresh_token",
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Google token refresh failed: {resp.status_code} {resp.text[:200]}"
        )
    return str(resp.json().get("access_token", ""))


async def _gsheets_ensure_header(
    client: httpx.AsyncClient,
    config: Any,
    access_token: str,
) -> None:
    """Append a header row if the sheet is empty."""
    sheet = config.sheet_name or "DistroAgent"
    sid = config.spreadsheet_id
    check = await client.get(
        f"{_GSHEETS_API_BASE}/{sid}/values/{sheet}!A1",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if check.status_code == 200:
        values = check.json().get("values", [])
        if values:
            return  # header already exists

    header = [
        "Timestamp", "Event Type", "Store Name", "Store Email", "Address",
        "Lead Score", "Email ID", "Email Subject", "Reply Intent",
        "Meeting Time", "Meeting URL", "Invoice ID", "Amount USD",
    ]
    await client.post(
        f"{_GSHEETS_API_BASE}/{sid}/values/{sheet}!A1:append?valueInputOption=USER_ENTERED",
        json={"values": [header]},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )


async def _push_google_sheets(event: CrmEvent, config: Any) -> None:
    if not config.spreadsheet_id:
        logger.warning("crm_sheets_missing_spreadsheet_id", tenant_id=event.tenant_id)
        return

    sheet = config.sheet_name or "DistroAgent"
    sid = config.spreadsheet_id

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        access_token = await _gsheets_get_access_token(client, config)
        await _gsheets_ensure_header(client, config, access_token)

        row = event.to_sheet_row()
        resp = await client.post(
            f"{_GSHEETS_API_BASE}/{sid}/values/{sheet}!A1:append?valueInputOption=USER_ENTERED",
            json={"values": [row]},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code not in (200, 201):
        logger.warning(
            "crm_sheets_append_failed",
            status_code=resp.status_code,
            tenant_id=event.tenant_id,
        )
        return

    logger.info(
        "crm_sheets_pushed",
        event_type=event.event_type.value,
        spreadsheet_id=sid,
        tenant_id=event.tenant_id,
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_ADAPTERS = {
    "webhook": _push_webhook,
    "hubspot": _push_hubspot,
    "salesforce": _push_salesforce,
    "google_sheets": _push_google_sheets,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def push_event(
    tenant_id: str,
    event_type: CrmEventType,
    event_data: dict[str, Any],
    db: AsyncSession | None = None,
) -> None:
    """Push a CRM event to the tenant's configured endpoint.

    Never raises — all failures are logged and swallowed so the calling
    agent node or service function is never disrupted by a CRM outage.

    Args:
        tenant_id:  Tenant UUID as string. Empty string → silently skip.
        event_type: One of the CrmEventType enum values.
        event_data: Dict of optional fields that populate CrmEvent (store_name,
                    store_email, email_id, amount_usd, meeting_url, etc.).
        db:         Optional async session. A fresh one is created if None.
    """
    if not tenant_id:
        return

    try:
        if db is not None:
            await _push_with_session(tenant_id, event_type, event_data, db)
        else:
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                await _push_with_session(tenant_id, event_type, event_data, session)
    except Exception as exc:
        logger.error(
            "crm_sync_unhandled_error",
            tenant_id=tenant_id,
            event_type=event_type,
            error=str(exc),
        )


async def _push_with_session(
    tenant_id: str,
    event_type: CrmEventType,
    event_data: dict[str, Any],
    db: AsyncSession,
) -> None:
    config = await _get_config(tenant_id, db)
    if config is None:
        logger.debug("crm_sync_no_config", tenant_id=tenant_id, event_type=event_type)
        return

    adapter = _ADAPTERS.get(config.crm_type)
    if adapter is None:
        logger.warning(
            "crm_sync_unknown_crm_type",
            crm_type=config.crm_type,
            tenant_id=tenant_id,
        )
        return

    event = CrmEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        **event_data,
    )

    try:
        await adapter(event, config)
    except Exception as exc:
        logger.error(
            "crm_sync_adapter_error",
            crm_type=config.crm_type,
            event_type=event_type.value,
            tenant_id=tenant_id,
            error=str(exc),
        )
