"""Tests for metrics_service.compute_tenant_kpis — all DB calls mocked."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.models.user  # noqa: F401 — satisfies Tenant.users relationship at mapper config time
from app.schemas.metrics import KpiSummary
from app.services.metrics_service import compute_tenant_kpis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _make_db(counts: list[int]) -> AsyncMock:
    """Return an AsyncSession mock whose execute() yields scalar counts in order.

    execute() call order in compute_tenant_kpis:
    0: leads_discovered, 1: leads_qualified, 2: emails_sent,
    3: replies, 4: positive_replies, 5: meetings_booked, 6: deals_closed
    """
    db = AsyncMock()
    db.execute.side_effect = [_scalar_result(c) for c in counts]
    return db


_ZEROS = [0, 0, 0, 0, 0, 0, 0]


# ---------------------------------------------------------------------------
# Aggregation correctness
# ---------------------------------------------------------------------------


class TestComputeTenantKpis:
    @pytest.mark.asyncio
    async def test_basic_aggregation(self) -> None:
        db = _make_db([10, 4, 8, 3, 2, 1, 0])
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db)

        assert kpis.leads_discovered == 10
        assert kpis.leads_qualified == 4
        assert kpis.emails_sent == 8
        assert kpis.reply_rate == pytest.approx(3 / 8, rel=1e-3)
        assert kpis.positive_reply_rate == pytest.approx(2 / 8, rel=1e-3)
        assert kpis.meetings_booked == 1
        assert kpis.booking_rate == pytest.approx(1 / 8, rel=1e-3)
        assert kpis.deals_closed == 0

    @pytest.mark.asyncio
    async def test_lookback_days_propagated(self) -> None:
        db = _make_db(_ZEROS)
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=7, db=db)
        assert kpis.lookback_days == 7

    @pytest.mark.asyncio
    async def test_generated_at_is_datetime(self) -> None:
        db = _make_db(_ZEROS)
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db)
        assert isinstance(kpis.generated_at, datetime)

    @pytest.mark.asyncio
    async def test_returns_kpi_summary_instance(self) -> None:
        db = _make_db(_ZEROS)
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db)
        assert isinstance(kpis, KpiSummary)

    @pytest.mark.asyncio
    async def test_all_fields_present(self) -> None:
        await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=_make_db([5, 2, 4, 1, 1, 1, 1]))

        required = {
            "leads_discovered", "leads_qualified", "emails_sent",
            "reply_rate", "positive_reply_rate", "meetings_booked",
            "booking_rate", "deals_closed", "total_cost_usd",
            "cost_per_lead", "lookback_days", "generated_at",
        }
        assert required == set(KpiSummary.model_fields.keys())


# ---------------------------------------------------------------------------
# Division-by-zero guards
# ---------------------------------------------------------------------------


class TestDivisionByZeroGuards:
    @pytest.mark.asyncio
    async def test_zero_emails_gives_zero_reply_rate(self) -> None:
        db = _make_db([5, 2, 0, 0, 0, 0, 0])
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db)

        assert kpis.reply_rate == 0.0
        assert kpis.positive_reply_rate == 0.0
        assert kpis.booking_rate == 0.0

    @pytest.mark.asyncio
    async def test_zero_leads_gives_zero_cost_per_lead(self) -> None:
        db = _make_db(_ZEROS)
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db)

        assert kpis.cost_per_lead == 0.0

    @pytest.mark.asyncio
    async def test_all_zeros_no_exception(self) -> None:
        db = _make_db(_ZEROS)
        kpis = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db)

        assert kpis.leads_discovered == 0
        assert kpis.emails_sent == 0
        assert kpis.reply_rate == 0.0


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_two_tenants_get_independent_kpis(self) -> None:
        """Each call is parameterised by its own tenant_id — results must not bleed."""
        db_a = _make_db([10, 5, 8, 2, 1, 1, 0])
        db_b = _make_db([3, 1, 2, 0, 0, 0, 0])

        kpis_a = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db_a)
        kpis_b = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db_b)

        assert kpis_a.leads_discovered == 10
        assert kpis_b.leads_discovered == 3
        assert kpis_a.emails_sent == 8
        assert kpis_b.emails_sent == 2

    @pytest.mark.asyncio
    async def test_tenant_a_nonzero_tenant_b_zero(self) -> None:
        """A tenant with no data returns all-zero rates regardless of other tenants."""
        db_a = _make_db([20, 10, 15, 5, 3, 2, 1])
        db_b = _make_db(_ZEROS)

        kpis_a = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db_a)
        kpis_b = await compute_tenant_kpis(tenant_id=uuid.uuid4(), lookback_days=30, db=db_b)

        assert kpis_a.reply_rate > 0
        assert kpis_b.reply_rate == 0.0
