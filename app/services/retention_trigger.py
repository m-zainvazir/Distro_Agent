"""Retention sweep — find closed deals and fire the Retention agent per buyer.

Invoked by `POST /retention/run` (an external cron hits it daily) so it runs
inside the single live Railway service — no Celery worker/beat required.

For each closed deal older than the minimum window, the Retention agent assesses
estimated sell-through and, when stock is low, drafts a restock pitch through the
shared HITL gate (which also emits the RESTOCK_OPPORTUNITY CRM event). Deals that
actually trigger a pitch are flipped `deal_status -> "restock_pitched"` so they are
not re-pitched on the next sweep; deals not yet due stay `deal_closed` and are
re-evaluated later (more elapsed days → eventually crosses the restock threshold).

NOTE: order size and daily sell-through rate are not yet persisted anywhere, so
they use documented module defaults until inventory data is integrated (Layer 10).
The elapsed-time component of the assessment is real (deal close date).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.campaign import OutreachEmail, StoreCandidate

# Tuning (estimates until real order/inventory data is wired in).
_MIN_DAYS_SINCE_CLOSE = 30      # give the retailer time to sell through first
_DEFAULT_UNITS_ORDERED = 100
_DEFAULT_AVG_DAILY_SALES = 1.5
_RESTOCK_THRESHOLD_PCT = 20.0
_SCAN_LIMIT = 100              # cap rows per sweep so a cron call stays bounded

_CLOSED = "deal_closed"
_PITCHED = "restock_pitched"


def _retention_state(email: OutreachEmail, store: StoreCandidate, thread_id: str) -> dict:
    last_order = (email.updated_at or datetime.utcnow()).isoformat()
    return {
        "tenant_id": str(email.tenant_id),
        "store_name": store.name,
        "buyer_email": email.to_email or "",
        "buyer_name": store.name,
        "last_order_date": last_order,
        "units_ordered": _DEFAULT_UNITS_ORDERED,
        "avg_daily_sales": _DEFAULT_AVG_DAILY_SALES,
        "restock_threshold_pct": _RESTOCK_THRESHOLD_PCT,
        "days_since_order": 0.0,
        "estimated_units_sold": 0.0,
        "estimated_remaining_units": 0.0,
        "sellthrough_pct": 0.0,
        "estimated_days_to_stockout": 0.0,
        "needs_restock": False,
        "restock_pitch": "",
        "approved": None,
        "routing_action": "",
        "graph_thread_id": thread_id,
    }


async def run_retention_sweep(db: AsyncSession) -> dict:
    """Scan closed deals and run the Retention agent for each. Returns a summary."""
    from app.agents.retention_agent import build_retention_graph
    from app.core.checkpointer import get_checkpointer

    # updated_at is TIMESTAMP WITHOUT TIME ZONE — compare against a naive UTC cutoff.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_MIN_DAYS_SINCE_CLOSE)).replace(
        tzinfo=None
    )

    result = await db.execute(
        select(OutreachEmail, StoreCandidate)
        .join(StoreCandidate, OutreachEmail.store_id == StoreCandidate.id)
        .where(
            OutreachEmail.deal_status == _CLOSED,
            OutreachEmail.updated_at <= cutoff,
        )
        .limit(_SCAN_LIMIT)
    )
    rows = result.all()

    checkpointer = await get_checkpointer()
    scanned = 0
    pitched = 0

    for email, store in rows:
        scanned += 1
        thread_id = f"retention-{email.id}"
        graph = build_retention_graph(checkpointer=checkpointer)
        try:
            run = await graph.ainvoke(
                _retention_state(email, store, thread_id),
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as exc:
            logger.error("retention_sweep_run_failed", email_id=str(email.id), error=str(exc))
            continue

        # A pitch is in flight when the graph paused for HITL approval, or (under
        # full_auto) ran straight through to notify.
        is_pitch = ("__interrupt__" in run) or (run.get("routing_action") == _PITCHED)
        if is_pitch:
            email.deal_status = _PITCHED
            pitched += 1

    if pitched:
        await db.commit()

    logger.info("retention_sweep_complete", scanned=scanned, pitched=pitched)
    return {"scanned": scanned, "pitched": pitched}
