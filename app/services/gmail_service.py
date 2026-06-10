"""Gmail API service — polls for inbound replies using OAuth2.

Security rules
--------------
- NEVER store passwords.  OAuth tokens (access token + refresh token) only.
- Refresh tokens are stored as environment variables, never in the database.
- Access tokens are short-lived (~1 h) and refreshed automatically on each poll.
- Credentials scope: gmail.readonly (read only — never send from this service).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass
class ParsedReply:
    gmail_message_id: str
    gmail_thread_id: str
    sender: str
    subject: str
    body: str
    in_reply_to: str  # matches the Message-ID of the email we sent


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------


async def _refresh_access_token() -> str:
    """Exchange the stored refresh token for a new short-lived access token.

    Never touches a password — only the client credentials and refresh token
    configured via environment variables.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "client_id": settings.gmail_oauth_client_id,
                "client_secret": settings.gmail_oauth_client_secret,
                "refresh_token": settings.gmail_oauth_refresh_token,
                "grant_type": "refresh_token",
            },
        )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


# ---------------------------------------------------------------------------
# Payload parsing helpers
# ---------------------------------------------------------------------------


def _header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(payload: dict[str, Any]) -> str:
    """Recursively extract the plain-text body from a Gmail message payload."""
    body_data: str = payload.get("body", {}).get("data", "")
    if body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        nested = _decode_body(part)
        if nested:
            return nested

    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_new_replies(
    known_message_ids: set[str],
) -> list[ParsedReply]:
    """Poll Gmail inbox for replies to our outbound emails.

    Matches inbound messages whose ``In-Reply-To`` header equals one of the
    Message-IDs in *known_message_ids* (the IDs of emails we sent via
    SendGrid, stored in ``OutreachEmail.message_id``).

    Args:
        known_message_ids: Set of outbound Message-IDs to match against.

    Returns:
        List of :class:`ParsedReply` objects for unprocessed inbound messages.
    """
    if not settings.gmail_oauth_refresh_token:
        logger.warning("gmail_oauth_not_configured")
        return []

    try:
        access_token = await _refresh_access_token()
    except Exception as exc:
        logger.error("gmail_token_refresh_failed", error=str(exc))
        return []

    auth_headers = {"Authorization": f"Bearer {access_token}"}
    replies: list[ParsedReply] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        list_resp = await client.get(
            f"{_GMAIL_API}/users/me/messages",
            headers=auth_headers,
            params={"q": "in:inbox", "maxResults": 50},
        )
        if list_resp.status_code != 200:
            logger.error("gmail_list_failed", status=list_resp.status_code)
            return []

        messages: list[dict[str, Any]] = list_resp.json().get("messages", [])

        for msg in messages:
            msg_id: str = msg["id"]

            detail_resp = await client.get(
                f"{_GMAIL_API}/users/me/messages/{msg_id}",
                headers=auth_headers,
                params={"format": "full"},
            )
            if detail_resp.status_code != 200:
                continue

            data: dict[str, Any] = detail_resp.json()
            hdrs: list[dict[str, str]] = data.get("payload", {}).get("headers", [])

            in_reply_to = _header(hdrs, "In-Reply-To").strip("<>")
            if not in_reply_to or in_reply_to not in known_message_ids:
                continue

            replies.append(
                ParsedReply(
                    gmail_message_id=msg_id,
                    gmail_thread_id=data.get("threadId", ""),
                    sender=_header(hdrs, "From"),
                    subject=_header(hdrs, "Subject"),
                    body=_decode_body(data.get("payload", {})),
                    in_reply_to=in_reply_to,
                )
            )

    logger.info("gmail_replies_fetched", count=len(replies))
    return replies
