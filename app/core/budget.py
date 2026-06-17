"""Per-lead token/cost budget — enforces the 85%+ DFY margin rule (Blueprint Layers 14 & 16).

LeadBudget is in-memory per graph run. Pass an instance into each LLM-calling
node to gate expensive paths before they run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import logger


@dataclass
class LeadBudget:
    """Tracks cumulative token + cost spend for a single lead's agent journey.

    Usage pattern:
        budget = LeadBudget(lead_id=..., max_tokens=settings.max_tokens_per_lead,
                            max_cost_usd=settings.max_cost_per_lead_usd)

        if budget.check_and_reserve(estimated_cost, estimated_tokens):
            response = await llm_call(...)
            budget.record_usage(response.usage.total_tokens, actual_cost)
        else:
            # degrade gracefully
    """

    lead_id: str
    max_tokens: int
    max_cost_usd: float
    tokens_spent: int = field(default=0)
    cost_spent_usd: float = field(default=0.0)

    def check_and_reserve(
        self,
        estimated_cost: float,
        estimated_tokens: int = 0,
    ) -> bool:
        """Atomically check and reserve budget for an upcoming LLM call.

        Deducts *estimated_cost* and *estimated_tokens* from the remaining
        allowance. Returns False (without modifying state) if the cap would
        be exceeded, and logs ``lead_budget_exhausted``.
        """
        new_cost = self.cost_spent_usd + estimated_cost
        new_tokens = self.tokens_spent + estimated_tokens

        if new_cost > self.max_cost_usd:
            logger.warning(
                "lead_budget_exhausted",
                lead_id=self.lead_id,
                reason="cost_cap",
                cost_spent_usd=round(self.cost_spent_usd, 6),
                estimated_cost=estimated_cost,
                max_cost_usd=self.max_cost_usd,
            )
            return False

        if self.max_tokens > 0 and new_tokens > self.max_tokens:
            logger.warning(
                "lead_budget_exhausted",
                lead_id=self.lead_id,
                reason="token_cap",
                tokens_spent=self.tokens_spent,
                estimated_tokens=estimated_tokens,
                max_tokens=self.max_tokens,
            )
            return False

        self.cost_spent_usd = round(new_cost, 6)
        self.tokens_spent = new_tokens
        return True

    def record_usage(self, tokens: int, cost_usd: float) -> None:
        """Record actual LLM usage after a call.

        Use this for calls *not* pre-gated by check_and_reserve, or to
        reconcile actual vs. estimated spend after a call.
        """
        self.tokens_spent += tokens
        self.cost_spent_usd = round(self.cost_spent_usd + cost_usd, 6)
        logger.info(
            "lead_budget_usage_recorded",
            lead_id=self.lead_id,
            tokens_added=tokens,
            cost_added_usd=round(cost_usd, 6),
            total_tokens=self.tokens_spent,
            total_cost_usd=self.cost_spent_usd,
        )

    @property
    def remaining_cost_usd(self) -> float:
        return round(self.max_cost_usd - self.cost_spent_usd, 6)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.tokens_spent)
