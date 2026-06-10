"""Tests for email_service and domain_service — all HTTP/DB calls mocked."""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from app.services.domain_service import daily_send_limit, record_bounce
from app.services.email_service import (
    DailySendCapExceeded,
    send_outreach_email,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.uuid4()
_CAMPAIGN_ID = uuid.uuid4()
_EMAIL_ID = uuid.uuid4()


def _make_email(outcome: str = "approved") -> MagicMock:
    e = MagicMock()
    e.id = _EMAIL_ID
    e.campaign_id = _CAMPAIGN_ID
    e.subject = "Wholesale opportunity for your store"
    e.body = "Hi there, we would love to partner with you."
    e.outcome = outcome
    e.to_email = "buyer@boutique.com"
    e.message_id = None
    e.sent_at = None
    return e


def _make_campaign(tenant_id: uuid.UUID = _TENANT_ID) -> MagicMock:
    c = MagicMock()
    c.id = _CAMPAIGN_ID
    c.tenant_id = tenant_id
    return c


def _make_domain(
    warmup_day: int = 14,
    emails_sent_today: int = 0,
    send_count: int = 50,
    bounce_count: int = 0,
) -> MagicMock:
    d = MagicMock()
    d.domain = "trybrand.com"
    d.warmup_day = warmup_day
    d.emails_sent_today = emails_sent_today
    d.send_count = send_count
    d.bounce_count = bounce_count
    d.paused = False
    d.last_send_date = date.today()
    return d


def _make_db(campaign: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = campaign
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test 1 — happy path: sends via SendGrid, updates outcome + message_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_send_outreach_email_sends_via_sendgrid() -> None:
    route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
        return_value=Response(202, headers={"X-Message-Id": "msg-xyz-789"})
    )

    email = _make_email(outcome="approved")
    campaign = _make_campaign()
    domain = _make_domain()
    db = _make_db(campaign=campaign)

    with patch("app.services.email_service.get_active_domain", return_value=domain), \
         patch("app.services.email_service.record_send", new_callable=AsyncMock):
        await send_outreach_email(email, db)

    assert route.called, "SendGrid endpoint was not called"
    sent_payload = route.calls[0].request
    assert "trybrand.com" in sent_payload.content.decode()

    assert email.outcome == "sent"
    assert email.message_id == "msg-xyz-789"
    assert email.sent_at is not None
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2 — guard rejects any non-approved email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_outreach_email_asserts_approved_status() -> None:
    for bad_outcome in ("pending", "pending_approval", "sent", "bounced"):
        email = _make_email(outcome=bad_outcome)
        with pytest.raises(AssertionError, match="approved"):
            await send_outreach_email(email, _make_db())


# ---------------------------------------------------------------------------
# Test 3 — daily cap exceeded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_outreach_email_raises_when_cap_exceeded() -> None:
    # warmup_day=14 → cap is 100; emails_sent_today=100 → cap hit
    domain = _make_domain(warmup_day=14, emails_sent_today=100)
    db = _make_db(campaign=_make_campaign())

    with patch("app.services.email_service.get_active_domain", return_value=domain):
        with pytest.raises(DailySendCapExceeded):
            await send_outreach_email(_make_email(), db)


# ---------------------------------------------------------------------------
# Test 4 — warmup schedule: day 1 = 10 emails
# ---------------------------------------------------------------------------


def test_daily_send_limit_warmup_day_1() -> None:
    domain = _make_domain(warmup_day=1)
    assert daily_send_limit(domain) == 10


# ---------------------------------------------------------------------------
# Test 5 — warmup schedule: day 14 = 100 emails (full ramp)
# ---------------------------------------------------------------------------


def test_daily_send_limit_warmup_day_14() -> None:
    domain = _make_domain(warmup_day=14)
    assert daily_send_limit(domain) == 100


# ---------------------------------------------------------------------------
# Test 6 — domain paused when bounce rate exceeds 5%
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_bounce_pauses_domain_above_threshold() -> None:
    # 5 bounces out of 100 sends = 5%; after increment: 6/100 = 6% → paused
    domain = _make_domain(send_count=100, bounce_count=5)
    domain.paused = False
    db = AsyncMock()
    db.commit = AsyncMock()

    await record_bounce(domain, db)

    assert domain.bounce_count == 6
    assert domain.paused is True
    assert "bounce rate" in domain.paused_reason.lower()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 7 — Celery task sends all approved emails
# ---------------------------------------------------------------------------


def test_celery_task_sends_approved_emails() -> None:
    from app.tasks.email_tasks import _send_approved_emails
    import asyncio

    email1 = _make_email(outcome="approved")
    email2 = _make_email(outcome="approved")
    email2.id = uuid.uuid4()

    async def _mock_send(email: MagicMock, db: AsyncMock) -> None:
        email.outcome = "sent"

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [email1, email2]
    mock_db.execute = AsyncMock(return_value=result_mock)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.AsyncSessionLocal", return_value=mock_ctx), \
         patch("app.services.email_service.send_outreach_email", side_effect=_mock_send):
        result = asyncio.run(_send_approved_emails())

    assert result["sent"] == 2
    assert result["errors"] == 0
    assert result["skipped"] == 0
