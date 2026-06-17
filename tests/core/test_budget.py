"""Tests for LeadBudget — exhaustion, reservation, tier-gating."""
from __future__ import annotations

import pytest

from app.core.budget import LeadBudget


# ---------------------------------------------------------------------------
# check_and_reserve — basic behaviour
# ---------------------------------------------------------------------------


class TestCheckAndReserve:
    def _budget(
        self,
        max_cost: float = 0.05,
        max_tokens: int = 4000,
        lead_id: str = "lead-001",
    ) -> LeadBudget:
        return LeadBudget(lead_id=lead_id, max_tokens=max_tokens, max_cost_usd=max_cost)

    def test_returns_true_within_cost_budget(self) -> None:
        b = self._budget(max_cost=0.05)
        assert b.check_and_reserve(estimated_cost=0.01) is True

    def test_deducts_estimated_cost(self) -> None:
        b = self._budget(max_cost=0.05)
        b.check_and_reserve(estimated_cost=0.02)
        assert b.cost_spent_usd == pytest.approx(0.02)

    def test_deducts_estimated_tokens(self) -> None:
        b = self._budget(max_tokens=1000)
        b.check_and_reserve(estimated_cost=0.0, estimated_tokens=300)
        assert b.tokens_spent == 300

    def test_returns_false_when_cost_would_exceed_cap(self) -> None:
        b = self._budget(max_cost=0.05)
        b.check_and_reserve(estimated_cost=0.04)  # spend 0.04
        assert b.check_and_reserve(estimated_cost=0.02) is False  # 0.06 > 0.05

    def test_returns_false_when_tokens_would_exceed_cap(self) -> None:
        b = self._budget(max_tokens=500)
        b.check_and_reserve(estimated_cost=0.0, estimated_tokens=400)
        assert b.check_and_reserve(estimated_cost=0.0, estimated_tokens=200) is False  # 600 > 500

    def test_exhausted_check_does_not_modify_state(self) -> None:
        b = self._budget(max_cost=0.05)
        b.check_and_reserve(estimated_cost=0.04)
        b.check_and_reserve(estimated_cost=0.02)  # fails
        assert b.cost_spent_usd == pytest.approx(0.04)
        assert b.tokens_spent == 0

    def test_exact_cap_still_succeeds(self) -> None:
        b = self._budget(max_cost=0.05)
        assert b.check_and_reserve(estimated_cost=0.05) is True
        assert b.cost_spent_usd == pytest.approx(0.05)

    def test_one_cent_over_cap_fails(self) -> None:
        b = self._budget(max_cost=0.05)
        b.check_and_reserve(estimated_cost=0.05)
        assert b.check_and_reserve(estimated_cost=0.001) is False

    def test_zero_max_tokens_skips_token_cap(self) -> None:
        """max_tokens=0 means no token limit — should not block the call."""
        b = self._budget(max_tokens=0, max_cost=1.0)
        assert b.check_and_reserve(estimated_cost=0.0, estimated_tokens=999_999) is True

    def test_multiple_sequential_reserves_accumulate(self) -> None:
        b = self._budget(max_cost=0.10)
        b.check_and_reserve(estimated_cost=0.03)
        b.check_and_reserve(estimated_cost=0.03)
        b.check_and_reserve(estimated_cost=0.03)
        assert b.cost_spent_usd == pytest.approx(0.09)
        assert b.check_and_reserve(estimated_cost=0.02) is False  # 0.11 > 0.10


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


class TestRecordUsage:
    def test_accumulates_tokens(self) -> None:
        b = LeadBudget(lead_id="x", max_tokens=1000, max_cost_usd=0.05)
        b.record_usage(tokens=100, cost_usd=0.01)
        b.record_usage(tokens=200, cost_usd=0.02)
        assert b.tokens_spent == 300
        assert b.cost_spent_usd == pytest.approx(0.03)

    def test_independent_of_check_and_reserve(self) -> None:
        b = LeadBudget(lead_id="x", max_tokens=1000, max_cost_usd=0.05)
        b.record_usage(tokens=500, cost_usd=0.02)
        assert b.check_and_reserve(estimated_cost=0.04) is False  # 0.06 > 0.05


# ---------------------------------------------------------------------------
# remaining_* properties
# ---------------------------------------------------------------------------


class TestRemainingProperties:
    def test_remaining_cost_decreases_after_reserve(self) -> None:
        b = LeadBudget(lead_id="x", max_tokens=1000, max_cost_usd=0.05)
        b.check_and_reserve(estimated_cost=0.02)
        assert b.remaining_cost_usd == pytest.approx(0.03)

    def test_remaining_tokens_decreases_after_reserve(self) -> None:
        b = LeadBudget(lead_id="x", max_tokens=1000, max_cost_usd=0.05)
        b.check_and_reserve(estimated_cost=0.0, estimated_tokens=300)
        assert b.remaining_tokens == 700

    def test_remaining_tokens_floors_at_zero(self) -> None:
        b = LeadBudget(lead_id="x", max_tokens=100, max_cost_usd=1.0)
        b.record_usage(tokens=150, cost_usd=0.0)
        assert b.remaining_tokens == 0


# ---------------------------------------------------------------------------
# Tier-gating (vision gate: score threshold AND budget)
# ---------------------------------------------------------------------------


class TestTierGating:
    """Simulates the analyst agent's combined score + budget gate."""

    _VISION_MIN_SCORE = 8.0
    _VISION_EST_COST = 0.0003

    def _try_vision(self, lead_score: float, budget: LeadBudget) -> bool:
        """Return True only if score gate AND budget gate both pass."""
        if lead_score < self._VISION_MIN_SCORE:
            return False
        return budget.check_and_reserve(self._VISION_EST_COST, estimated_tokens=400)

    def test_low_score_skips_vision_budget_untouched(self) -> None:
        b = LeadBudget(lead_id="low", max_tokens=4000, max_cost_usd=0.05)
        result = self._try_vision(lead_score=6.0, budget=b)
        assert result is False
        assert b.cost_spent_usd == 0.0  # budget never touched

    def test_high_score_within_budget_runs_vision(self) -> None:
        b = LeadBudget(lead_id="high", max_tokens=4000, max_cost_usd=0.05)
        result = self._try_vision(lead_score=9.5, budget=b)
        assert result is True
        assert b.cost_spent_usd == pytest.approx(self._VISION_EST_COST)

    def test_high_score_exhausted_budget_skips_vision(self) -> None:
        b = LeadBudget(lead_id="high-broke", max_tokens=4000, max_cost_usd=0.0001)
        b.check_and_reserve(estimated_cost=0.0001)  # exhaust budget
        result = self._try_vision(lead_score=9.5, budget=b)
        assert result is False

    def test_score_exactly_at_threshold_runs_vision(self) -> None:
        b = LeadBudget(lead_id="edge", max_tokens=4000, max_cost_usd=0.05)
        result = self._try_vision(lead_score=self._VISION_MIN_SCORE, budget=b)
        assert result is True

    def test_score_just_below_threshold_skips_vision(self) -> None:
        b = LeadBudget(lead_id="edge-low", max_tokens=4000, max_cost_usd=0.05)
        result = self._try_vision(lead_score=self._VISION_MIN_SCORE - 0.01, budget=b)
        assert result is False

    def test_budget_exhausted_after_multiple_leads(self) -> None:
        """Simulate multiple high-scoring leads exhausting the per-lead budget."""
        total_allowed = 3
        results = []
        for i in range(5):
            b = LeadBudget(
                lead_id=f"lead-{i}",
                max_tokens=4000,
                max_cost_usd=self._VISION_EST_COST * total_allowed,
            )
            # Pre-spend two slots worth to simulate prior calls on this lead
            b.check_and_reserve(self._VISION_EST_COST * 2)
            results.append(self._try_vision(lead_score=9.0, budget=b))

        # Only one slot remains (3 - 2 = 1), first five each have one slot → all pass
        assert all(results)
