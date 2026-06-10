"""Google Calendar API service — OAuth2, free-slot discovery, event creation.

Security rules
--------------
- NEVER store passwords.  OAuth tokens (access + refresh) only.
- Refresh tokens stored as environment variables, never in the database.
- Access tokens are short-lived (~1 h); refreshed automatically per call.
- Scope required: calendar.events (read + write for primary calendar).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
_BUSINESS_HOURS_START = 9   # 09:00 UTC
_BUSINESS_HOURS_END = 17    # 17:00 UTC


# ---------------------------------------------------------------------------
# OAuth helper
# ---------------------------------------------------------------------------


async def _refresh_access_token() -> str:
    """Exchange the stored refresh token for a new short-lived access token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "client_id": settings.google_calendar_oauth_client_id,
                "client_secret": settings.google_calendar_oauth_client_secret,
                "refresh_token": settings.google_calendar_oauth_refresh_token,
                "grant_type": "refresh_token",
            },
        )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


# ---------------------------------------------------------------------------
# Slot generation helpers
# ---------------------------------------------------------------------------


def _generate_slots(
    window_start: datetime,
    window_end: datetime,
    busy: list[dict[str, str]],
    duration_mins: int,
) -> list[dict[str, str]]:
    """Return all free duration_mins-long slots within business hours on weekdays."""
    busy_ranges: list[tuple[datetime, datetime]] = []
    for b in busy:
        b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        busy_ranges.append((b_start, b_end))

    delta = timedelta(minutes=duration_mins)
    free: list[dict[str, str]] = []

    # Advance cursor to the next clean 30-min boundary
    cursor = window_start.replace(second=0, microsecond=0)
    if cursor.minute % duration_mins != 0:
        remainder = duration_mins - (cursor.minute % duration_mins)
        cursor += timedelta(minutes=remainder)

    while cursor < window_end:
        slot_end = cursor + delta

        is_weekday = cursor.weekday() < 5
        in_hours = _BUSINESS_HOURS_START <= cursor.hour < _BUSINESS_HOURS_END
        fits = slot_end.hour <= _BUSINESS_HOURS_END
        overlaps = any(bs < slot_end and be > cursor for bs, be in busy_ranges)

        if is_weekday and in_hours and fits and not overlaps:
            free.append(
                {
                    "start": cursor.isoformat(),
                    "end": slot_end.isoformat(),
                }
            )

        cursor += delta

    return free


def _fmt_slot(slot: dict[str, str]) -> str:
    dt = datetime.fromisoformat(slot["start"])
    return dt.strftime("%A, %B %d at %I:%M %p UTC")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_free_slots(
    days_ahead: int = 7,
    slot_duration_mins: int = 30,
    max_slots: int = 10,
) -> list[dict[str, str]]:
    """Return up to *max_slots* available slots in the next *days_ahead* days.

    Each slot is a dict with ISO-8601 ``start`` and ``end`` keys.
    Returns an empty list if OAuth is not configured.
    """
    if not settings.google_calendar_oauth_refresh_token:
        logger.warning("calendar_oauth_not_configured")
        return []

    try:
        access_token = await _refresh_access_token()
    except Exception as exc:
        logger.error("calendar_token_refresh_failed", error=str(exc))
        return []

    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days_ahead)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_CALENDAR_API}/freeBusy",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "timeMin": now.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": "primary"}],
            },
        )

    if resp.status_code != 200:
        logger.error("calendar_freebusy_failed", status=resp.status_code)
        return []

    busy: list[dict[str, str]] = (
        resp.json().get("calendars", {}).get("primary", {}).get("busy", [])
    )
    slots = _generate_slots(now, time_max, busy, slot_duration_mins)
    logger.info("calendar_free_slots_found", count=len(slots))
    return slots[:max_slots]


async def create_event(
    slot: dict[str, str],
    attendee_emails: list[str],
    title: str,
    description: str = "",
) -> dict[str, str]:
    """Create a Google Calendar event with a Google Meet conference link.

    Returns a dict with ``event_id`` and ``meet_link``.
    """
    if not settings.google_calendar_oauth_refresh_token:
        logger.warning("calendar_oauth_not_configured")
        return {"event_id": "", "meet_link": ""}

    access_token = await _refresh_access_token()

    body: dict[str, Any] = {
        "summary": title,
        "description": description,
        "start": {"dateTime": slot["start"], "timeZone": "UTC"},
        "end": {"dateTime": slot["end"], "timeZone": "UTC"},
        "attendees": [{"email": e} for e in attendee_emails],
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"conferenceDataVersion": "1"},
            json=body,
        )

    if resp.status_code not in (200, 201):
        logger.error("calendar_create_event_failed", status=resp.status_code)
        raise RuntimeError(f"Calendar API returned {resp.status_code}")

    data = resp.json()
    entry_points: list[dict[str, str]] = (
        data.get("conferenceData", {}).get("entryPoints", [])
    )
    meet_link = next(
        (ep.get("uri", "") for ep in entry_points if "meet" in ep.get("uri", "")),
        entry_points[0].get("uri", "") if entry_points else "",
    )

    logger.info("calendar_event_created", event_id=data.get("id"), meet_link=meet_link)
    return {"event_id": data.get("id", ""), "meet_link": meet_link}
