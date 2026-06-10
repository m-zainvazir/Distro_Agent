from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WholesaleRulebook(BaseModel):
    """Per-tenant wholesale negotiation limits.

    Every counter-offer the Negotiator agent drafts must stay within these
    bounds.  Anything outside is escalated to the founder without an
    auto-counter being generated.
    """

    model_config = ConfigDict(frozen=True)

    min_order_quantity: int = 12
    wholesale_discount_max_pct: float = 50.0   # max % off retail price
    net_payment_days_max: int = 30              # e.g. Net 30
    free_shipping_threshold: float = 500.0     # order value in USD
    non_negotiables: list[str] = Field(default_factory=list)
    # e.g. ["consignment", "sale-or-return", "exclusive territory"]
