"""Tests for calibration_service and calibration_task — all DB calls mocked."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models.user  # noqa: F401 — satisfies Tenant.users relationship at mapper config time
from app.services.calibration_service import (
    _VISUAL_MAX,
    _VISUAL_MIN,
    _WEIGHT_NUDGE,
    _nudge_and_renormalize,
    calibrate_weights,
    classify_outcome,
    pearson_correlation,
)
from app.tasks.calibration_task import _format_report, _run_calibration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email(outcome: str = "sent", reply_intent: str | None = None) -> MagicMock:
    e = MagicMock()
    e.id = uuid.uuid4()
    e.outcome = outcome
    e.reply_intent = reply_intent
    e.store_id = uuid.uuid4()
    e.campaign_id = uuid.uuid4()
    e.sent_at = datetime.now(timezone.utc)
    return e


def _make_store(vibe_score: float = 5.0) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.vibe_score = vibe_score
    return s


def _make_weights_row(
    vertical: str = "all",
    visual: float = 0.35,
    category: float = 0.25,
    price: float = 0.20,
    engagement: float = 0.10,
    wholesale: float = 0.10,
    sample_size: int = 0,
) -> MagicMock:
    row = MagicMock(spec=["visual_weight", "category_weight", "price_weight",
                           "engagement_weight", "wholesale_weight",
                           "calibrated_at", "sample_size", "vertical_tag"])
    row.vertical_tag = vertical
    row.visual_weight = visual
    row.category_weight = category
    row.price_weight = price
    row.engagement_weight = engagement
    row.wholesale_weight = wholesale
    row.calibrated_at = None
    row.sample_size = sample_size
    return row


# ---------------------------------------------------------------------------
# classify_outcome
# ---------------------------------------------------------------------------


class TestClassifyOutcome:
    def test_converted_is_win(self) -> None:
        assert classify_outcome(_make_email(outcome="converted")) == "win"

    def test_interested_replied_is_win(self) -> None:
        assert classify_outcome(_make_email(outcome="replied", reply_intent="INTERESTED")) == "win"

    def test_meeting_request_replied_is_win(self) -> None:
        assert classify_outcome(_make_email(outcome="replied", reply_intent="MEETING_REQUEST")) == "win"

    def test_ignored_is_loss(self) -> None:
        assert classify_outcome(_make_email(outcome="ignored")) == "loss"

    def test_not_interested_replied_is_loss(self) -> None:
        assert classify_outcome(_make_email(outcome="replied", reply_intent="NOT_INTERESTED")) == "loss"

    def test_sent_no_reply_is_neutral(self) -> None:
        assert classify_outcome(_make_email(outcome="sent")) == "neutral"

    def test_pending_is_neutral(self) -> None:
        assert classify_outcome(_make_email(outcome="pending")) == "neutral"

    def test_objection_replied_is_neutral(self) -> None:
        # OBJECTION doesn't decide win/loss yet
        assert classify_outcome(_make_email(outcome="replied", reply_intent="OBJECTION")) == "neutral"


# ---------------------------------------------------------------------------
# pearson_correlation
# ---------------------------------------------------------------------------


class TestPearsonCorrelation:
    def test_empty_returns_zero(self) -> None:
        assert pearson_correlation([], []) == 0.0

    def test_single_element_returns_zero(self) -> None:
        assert pearson_correlation([1.0], [1.0]) == 0.0

    def test_perfect_positive_correlation(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = pearson_correlation(xs, ys)
        assert abs(r - 1.0) < 1e-9

    def test_perfect_negative_correlation(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        r = pearson_correlation(xs, ys)
        assert abs(r - (-1.0)) < 1e-9

    def test_no_variance_in_y_returns_zero(self) -> None:
        # All ys the same — denominator is zero
        xs = [1.0, 2.0, 3.0]
        ys = [1.0, 1.0, 1.0]
        assert pearson_correlation(xs, ys) == 0.0

    def test_moderate_positive_correlation(self) -> None:
        # High vibe → mostly wins, low vibe → mostly losses
        xs = [1.0, 2.0, 7.0, 8.0, 9.0]
        ys = [0.0, 0.0, 1.0, 1.0, 1.0]
        r = pearson_correlation(xs, ys)
        assert r > 0.8


# ---------------------------------------------------------------------------
# _nudge_and_renormalize
# ---------------------------------------------------------------------------


class TestNudgeAndRenormalize:
    def _default_row(self) -> MagicMock:
        return _make_weights_row()

    def test_high_correlation_increases_visual(self) -> None:
        row = self._default_row()
        changed = _nudge_and_renormalize(row, correlation=0.50)
        assert changed is True
        assert row.visual_weight == pytest.approx(0.35 + _WEIGHT_NUDGE, abs=1e-4)

    def test_low_correlation_decreases_visual(self) -> None:
        row = self._default_row()
        changed = _nudge_and_renormalize(row, correlation=0.02)
        assert changed is True
        assert row.visual_weight == pytest.approx(0.35 - _WEIGHT_NUDGE, abs=1e-4)

    def test_mid_correlation_no_change(self) -> None:
        row = self._default_row()
        changed = _nudge_and_renormalize(row, correlation=0.15)
        assert changed is False
        assert row.visual_weight == 0.35

    def test_weights_sum_to_one_after_increase(self) -> None:
        row = self._default_row()
        _nudge_and_renormalize(row, correlation=0.50)
        total = (
            row.visual_weight
            + row.category_weight
            + row.price_weight
            + row.engagement_weight
            + row.wholesale_weight
        )
        assert total == pytest.approx(1.0, abs=1e-3)

    def test_weights_sum_to_one_after_decrease(self) -> None:
        row = self._default_row()
        _nudge_and_renormalize(row, correlation=0.02)
        total = (
            row.visual_weight
            + row.category_weight
            + row.price_weight
            + row.engagement_weight
            + row.wholesale_weight
        )
        assert total == pytest.approx(1.0, abs=1e-3)

    def test_caps_at_visual_max(self) -> None:
        row = _make_weights_row(visual=_VISUAL_MAX, category=0.25,
                                price=0.20, engagement=0.10, wholesale=0.10)
        changed = _nudge_and_renormalize(row, correlation=0.90)
        assert changed is False
        assert row.visual_weight == _VISUAL_MAX

    def test_floors_at_visual_min(self) -> None:
        row = _make_weights_row(visual=_VISUAL_MIN, category=0.30,
                                price=0.25, engagement=0.13, wholesale=0.12)
        changed = _nudge_and_renormalize(row, correlation=0.01)
        assert changed is False
        assert row.visual_weight == _VISUAL_MIN


# ---------------------------------------------------------------------------
# calibrate_weights (DB mocked)
# ---------------------------------------------------------------------------


def _mock_db_with_rows(
    email_store_pairs: list[tuple[MagicMock, MagicMock]],
    existing_weights_row: MagicMock | None = None,
) -> AsyncMock:
    """Return an AsyncSession mock whose execute() returns the given rows."""
    db = AsyncMock()

    # First execute() → email/store join result
    email_result = MagicMock()
    email_result.all.return_value = email_store_pairs

    # Second execute() → ScoringWeights lookup
    weights_result = MagicMock()
    weights_result.scalar_one_or_none.return_value = existing_weights_row

    db.execute.side_effect = [email_result, weights_result]
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


class TestCalibrateWeights:
    @pytest.mark.asyncio
    async def test_no_update_when_sample_below_minimum(self) -> None:
        pairs = [
            (_make_email(outcome="converted"), _make_store(vibe_score=8.0)),
            (_make_email(outcome="ignored"), _make_store(vibe_score=2.0)),
        ]  # only 2 decided — below _MIN_SAMPLE
        row = _make_weights_row()
        db = _mock_db_with_rows(pairs, existing_weights_row=row)

        report = await calibrate_weights("all", db)

        assert report["weights_updated"] is False
        assert report["sample_size"] == 2
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_when_high_correlation(self) -> None:
        # 10+ decided outcomes, high vibe → win
        pairs = (
            [(_make_email(outcome="converted"), _make_store(vibe_score=9.0))] * 7
            + [(_make_email(outcome="ignored"), _make_store(vibe_score=1.0))] * 5
        )
        row = _make_weights_row()
        db = _mock_db_with_rows(pairs, existing_weights_row=row)

        report = await calibrate_weights("all", db)

        assert report["weights_updated"] is True
        assert report["new_visual_weight"] > report["old_visual_weight"]
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_when_low_correlation(self) -> None:
        # All stores scored similarly regardless of outcome → near-zero correlation
        pairs = (
            [(_make_email(outcome="converted"), _make_store(vibe_score=5.0))] * 5
            + [(_make_email(outcome="ignored"), _make_store(vibe_score=5.0))] * 7
        )
        row = _make_weights_row()
        db = _mock_db_with_rows(pairs, existing_weights_row=row)

        report = await calibrate_weights("all", db)

        # r ≈ 0 → low correlation branch → decrease visual weight
        assert report["visual_correlation"] == pytest.approx(0.0, abs=0.01)
        assert report["weights_updated"] is True
        assert report["new_visual_weight"] < report["old_visual_weight"]

    @pytest.mark.asyncio
    async def test_creates_new_row_when_none_exists(self) -> None:
        pairs = [(_make_email(outcome="converted"), _make_store(vibe_score=8.0))] * 11
        db = _mock_db_with_rows(pairs, existing_weights_row=None)

        report = await calibrate_weights("all", db)

        db.add.assert_called_once()
        assert report["vertical_tag"] == "all"

    @pytest.mark.asyncio
    async def test_neutral_emails_excluded_from_sample(self) -> None:
        neutral_pairs = [(_make_email(outcome="sent"), _make_store(vibe_score=5.0))] * 20
        db = _mock_db_with_rows(neutral_pairs, existing_weights_row=_make_weights_row())

        report = await calibrate_weights("all", db)

        assert report["sample_size"] == 0
        assert report["weights_updated"] is False

    @pytest.mark.asyncio
    async def test_report_structure_complete(self) -> None:
        pairs = [(_make_email(outcome="converted"), _make_store(vibe_score=7.0))] * 12
        db = _mock_db_with_rows(pairs, existing_weights_row=_make_weights_row())

        report = await calibrate_weights("footwear", db)

        required_keys = {
            "vertical_tag", "lookback_days", "total_emails", "wins", "losses",
            "neutral", "conversion_rate_pct", "sample_size", "visual_correlation",
            "bucket_win_rates", "weights_updated", "old_visual_weight",
            "new_visual_weight", "current_weights",
        }
        assert required_keys.issubset(set(report.keys()))
        assert set(report["bucket_win_rates"].keys()) == {"0-2", "2-4", "4-6", "6-8", "8-10"}
        assert set(report["current_weights"].keys()) == {
            "visual", "category", "price", "engagement", "wholesale"
        }


# ---------------------------------------------------------------------------
# _format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _sample_report(self, updated: bool = True) -> dict:
        return {
            "vertical_tag": "skincare",
            "total_emails": 25,
            "wins": 5,
            "losses": 10,
            "neutral": 10,
            "conversion_rate_pct": 20.0,
            "visual_correlation": 0.42,
            "sample_size": 15,
            "bucket_win_rates": {
                "0-2": "0% (2 emails)",
                "2-4": "10% (5 emails)",
                "4-6": "20% (5 emails)",
                "6-8": "40% (5 emails)",
                "8-10": "75% (4 emails)",
            },
            "weights_updated": updated,
            "old_visual_weight": 0.35,
            "new_visual_weight": 0.40 if updated else 0.35,
        }

    def test_contains_vertical_tag(self) -> None:
        msg = _format_report([self._sample_report()])
        assert "skincare" in msg

    def test_contains_conversion_rate(self) -> None:
        msg = _format_report([self._sample_report()])
        assert "20.0%" in msg

    def test_shows_weight_update_when_changed(self) -> None:
        msg = _format_report([self._sample_report(updated=True)])
        # Python formats 0.40 as "0.4" in f-strings
        assert "0.35 -> 0.4" in msg

    def test_shows_unchanged_message_when_not_updated(self) -> None:
        msg = _format_report([self._sample_report(updated=False)])
        assert "Weights unchanged" in msg

    def test_multiple_verticals_all_present(self) -> None:
        reports = [self._sample_report(), {**self._sample_report(), "vertical_tag": "footwear"}]
        msg = _format_report(reports)
        assert "skincare" in msg
        assert "footwear" in msg


# ---------------------------------------------------------------------------
# _run_calibration (integration-level, all DB and WhatsApp mocked)
# ---------------------------------------------------------------------------


class TestRunCalibration:
    @pytest.mark.asyncio
    async def test_runs_all_vertical_plus_global(self) -> None:
        verticals_queried: list[str] = []

        async def fake_calibrate(
            vertical_tag: str, db: object, **kwargs: object
        ) -> dict:
            verticals_queried.append(vertical_tag)
            return {
                "vertical_tag": vertical_tag,
                "total_emails": 5,
                "wins": 2,
                "losses": 1,
                "neutral": 2,
                "conversion_rate_pct": 40.0,
                "sample_size": 3,
                "visual_correlation": 0.3,
                "bucket_win_rates": {},
                "weights_updated": False,
                "old_visual_weight": 0.35,
                "new_visual_weight": 0.35,
            }

        # Mock vertical_tag query returning ["footwear"]
        vertical_result = MagicMock()
        vertical_result.all.return_value = [("footwear",)]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=vertical_result)

        # _run_calibration imports these locally, so patch at the source module.
        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch(
                "app.services.calibration_service.calibrate_weights",
                side_effect=fake_calibrate,
            ),
            patch(
                "app.services.whatsapp_service.send_deal_alert",
                new_callable=AsyncMock,
            ),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = ""  # skip WhatsApp for this test
            result = await _run_calibration()

        assert "footwear" in verticals_queried
        assert "all" in verticals_queried
        assert result["verticals_calibrated"] == 2

    @pytest.mark.asyncio
    async def test_sends_whatsapp_when_phone_configured(self) -> None:
        vertical_result = MagicMock()
        vertical_result.all.return_value = []

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=vertical_result)

        fake_report = {
            "vertical_tag": "all",
            "total_emails": 20,
            "wins": 5,
            "losses": 8,
            "neutral": 7,
            "conversion_rate_pct": 25.0,
            "sample_size": 13,
            "visual_correlation": 0.28,
            "bucket_win_rates": {},
            "weights_updated": False,
            "old_visual_weight": 0.35,
            "new_visual_weight": 0.35,
        }

        send_alert = AsyncMock()
        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch(
                "app.services.calibration_service.calibrate_weights",
                return_value=fake_report,
            ),
            patch("app.services.whatsapp_service.send_deal_alert", send_alert),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = "+15551234567"
            await _run_calibration()

        send_alert.assert_called_once()
        call_kwargs = send_alert.call_args
        assert call_kwargs.kwargs["phone"] == "+15551234567"

    @pytest.mark.asyncio
    async def test_continues_on_vertical_error(self) -> None:
        vertical_result = MagicMock()
        vertical_result.all.return_value = [("broken_vertical",)]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=vertical_result)

        call_count = 0

        async def flaky_calibrate(vertical_tag: str, db: object, **kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if vertical_tag == "broken_vertical":
                raise RuntimeError("DB exploded")
            return {
                "vertical_tag": vertical_tag, "total_emails": 0,
                "wins": 0, "losses": 0, "neutral": 0,
                "conversion_rate_pct": 0, "sample_size": 0,
                "visual_correlation": 0, "bucket_win_rates": {},
                "weights_updated": False, "old_visual_weight": 0.35,
                "new_visual_weight": 0.35,
            }

        with (
            patch("app.core.database.AsyncSessionLocal", return_value=mock_db),
            patch(
                "app.services.calibration_service.calibrate_weights",
                side_effect=flaky_calibrate,
            ),
            patch(
                "app.services.whatsapp_service.send_deal_alert",
                new_callable=AsyncMock,
            ),
            patch("app.core.config.settings") as mock_settings,
        ):
            mock_settings.whatsapp_founder_phone = ""
            result = await _run_calibration()

        # "broken_vertical" errored, "all" succeeded → 1 report
        assert result["verticals_calibrated"] == 1
        assert call_count == 2  # both verticals attempted
