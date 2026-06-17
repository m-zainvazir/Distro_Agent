from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KpiSummary(BaseModel):
    leads_discovered: int
    leads_qualified: int
    emails_sent: int
    reply_rate: float
    positive_reply_rate: float
    meetings_booked: int
    booking_rate: float
    deals_closed: int
    total_cost_usd: float
    cost_per_lead: float
    lookback_days: int
    generated_at: datetime
