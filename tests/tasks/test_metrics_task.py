"""Tests for metrics_task._format_kpi_digest and _run_metrics_digest.

Mirrors the calibration_task test pattern — all DB and WhatsApp calls mocked.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models.user  # noqa: F401 — satisfies Tenant.users relationship at mapper config time
from app.schemas.metrics import KpiSummary
from app.tasks.metrics_task import _format_kpi_digest, _run_metrics_digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _make_kpis(**overrides: object) -> KpiSummary:
    defaults: dict = dict(
        leads_discovered=10,
        leads_qualified=4,
        emails_sent=8,
        reply_rate=0.375,
        positive_reply_rate=0.25,
        meetings_booked=1,
        booking_rate=0.125,
        deals_closed=0,
        total_cost_usd=0.0,
        cost_per_lead=0.0,
        lookback_days=30,
        generated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return KpiSummary(**defaults)


def _make_tenant(phone: str | None = "+15551234567") -> MagicMock:
    t = MagicMock()
    t.id = uuid.uuid4()
    t.whatsapp_number = phone
    return t


# ---------------------------------------------------------------------------
# _format_kpi_digest
# ---------------------------------------------------------------------------


class TestFormatKpiDigest:
    def test_contains_lookback_days(self) -> None:
        msg = _format_kpi_digest(_make_kpis())
        assert "30" in msg

    def test_contains_emails_sent(self) -> None:
        msg = _format_kpi_digest(_make_kpis())
        assert "8" in msg

    def test_contains_reply_rate_percentage(self) -> None:
        msg = _format_kpi_digest(_make_kpis(reply_rate=0.375))
        assert "37.5%" in msg

    def test_contains_deals_closed_label(self) -> None:
        msg = _format_kpi_digest(_make_kpis())
        assert "Deals closed" in msg

    def test_contains_leads_discovered(self) -> None:
        msg = _format_kpi_digest(_make_kpis(leads_discovered=42))
        assert "42" in msg


# ---------------------------------------------------------------------------
# _run_metrics_digest (all DB and WhatsApp mocked)
# ---------------------------------------------------------------------------


class TestRunMetricsDigest:
    @pytest.mark.asyncio
    async def test_sends_digest_for_tenant_with_phone(self) -> None:
        tenant = _make_tenant(phone="+15551234567")
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = [tenant]

        db_counts = [10, 4, 8, 3, 2, 1, 0]
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute.side_effect = [
            scalars_result,
            *[_scalar_result(c) for c in db_counts],
        ]

        send_alert = AsyncMock()
        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch("app.services.whatsapp_service.send_deal_alert", send_alert),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = ""
            result = await _run_metrics_digest()

        assert result["tenants_notified"] == 1
        send_alert.assert_called_once()
        call_kwargs = send_alert.call_args.kwargs
        assert call_kwargs["phone"] == "+15551234567"
        assert call_kwargs["store_name"] == "DistroAgent KPIs"

    @pytest.mark.asyncio
    async def test_skips_tenant_without_phone(self) -> None:
        tenant = _make_tenant(phone=None)
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = [tenant]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=scalars_result)

        send_alert = AsyncMock()
        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch("app.services.whatsapp_service.send_deal_alert", send_alert),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = ""
            result = await _run_metrics_digest()

        assert result["tenants_notified"] == 0
        send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_founder_phone_when_tenant_has_none(self) -> None:
        tenant = _make_tenant(phone=None)
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = [tenant]

        db_counts = [0, 0, 0, 0, 0, 0, 0]
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute.side_effect = [
            scalars_result,
            *[_scalar_result(c) for c in db_counts],
        ]

        send_alert = AsyncMock()
        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch("app.services.whatsapp_service.send_deal_alert", send_alert),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = "+19998887777"
            result = await _run_metrics_digest()

        assert result["tenants_notified"] == 1
        assert send_alert.call_args.kwargs["phone"] == "+19998887777"

    @pytest.mark.asyncio
    async def test_continues_on_tenant_error(self) -> None:
        tenants = [_make_tenant("+15551111111"), _make_tenant("+15552222222")]
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = tenants

        call_count = 0

        async def flaky_compute(**kwargs: object) -> KpiSummary:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB exploded on first tenant")
            return _make_kpis()

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=scalars_result)

        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch("app.services.metrics_service.compute_tenant_kpis", side_effect=flaky_compute),
            patch("app.services.whatsapp_service.send_deal_alert", AsyncMock()),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = ""
            result = await _run_metrics_digest()

        assert result["tenants_notified"] == 1
        assert call_count == 2
