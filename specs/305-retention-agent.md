# Spec: P1 — Retention / Restock Agent (Layer 10)

## Overview
Blueprint Layer 10 calls for a **Retention Agent** that "monitors retailer sell-through
rates and autonomously pitches restock orders to maximize long-term buyer LTV." After a
wholesale deal closes, this agent estimates how much of the retailer's order has sold
through over time and, when stock is running low, drafts a personalised restock pitch —
routed through the **existing shared HITL gate** — then emits the **already-defined**
`CrmEventType.RESTOCK_OPPORTUNITY` event so the founder's CRM stays in sync.

No new external dependency, no LLM: the assessment is deterministic (free-tier friendly)
and the pitch is a template, mirroring the Scheduling agent.

## Files to create / modify
| File | Purpose |
|---|---|
| `app/agents/retention_agent.py` | `RetentionState` + LangGraph StateGraph + `build_retention_graph()` |
| `app/core/resume.py` (modify) | Add a `retention` branch so approve/reject resumes the graph |
| `app/workflows/registry.py` (modify) | Export `build_retention_graph` (checkpointer-requiring, like phase2) |
| `tests/agents/test_retention_agent.py` | Sell-through math + guardrail + HITL + CRM emission |

## State (`RetentionState`)
`tenant_id, store_name, buyer_email, buyer_name, last_order_date (ISO), units_ordered,
avg_daily_sales, restock_threshold_pct, days_since_order, estimated_units_sold,
estimated_remaining_units, sellthrough_pct, estimated_days_to_stockout, needs_restock,
restock_pitch, approved (HITL), routing_action, graph_thread_id`.

## Nodes
1. `assess_sellthrough` → compute days since order, estimated units sold
   (`avg_daily_sales × days`, capped at `units_ordered`), remaining units, sell-through %,
   and `needs_restock = remaining ≤ units_ordered × threshold`. Guards divide-by-zero
   (units_ordered ≤ 0 or avg_daily_sales ≤ 0 → no restock).
2. `route_after_assessment` → `draft_pitch` if `needs_restock` else `END`.
3. `draft_pitch` → compose a restock pitch email (deterministic template), register the
   pending approval (`graph_type="retention"`), send the WhatsApp card, then gate through
   `request_human_approval(action_class=ROUTINE_OUTREACH, autonomy_mode=...)`.
4. `route_after_pitch` → `notify` if approved else `END`.
5. `notify` → send a founder WhatsApp alert and emit `CrmEventType.RESTOCK_OPPORTUNITY`
   (store_name, store_email, restock_days). `routing_action = "restock_pitched"`.

## Behavior / classification
- The restock pitch is **warm** outreach to an existing happy buyer → classed
  `ROUTINE_OUTREACH` (auto-sends under `semi_auto`/`full_auto`, interrupts in `assist`),
  honouring the blueprint's "autonomously pitches restock orders" intent.
- CRM push uses the **existing** `push_event` (never raises) and the **existing**
  `RESTOCK_OPPORTUNITY` enum — no new CRM plumbing.

## Critical Rules
- Reuse the shared HITL gate (`request_human_approval`) — no bespoke approval path.
- Emit only the existing `CrmEventType.RESTOCK_OPPORTUNITY`; CRM failures must not break the graph.
- All thresholds are inputs/defaults, never hardcoded magic in the pitch.
- Type hints on every function; `make lint` clean; filter by `tenant_id` on any tenant write.

## Acceptance Criteria
- [ ] Sell-through assessment is correct and divide-by-zero safe (pure, unit-tested)
- [ ] `needs_restock` true only when remaining ≤ threshold; below-threshold ends the graph
- [ ] Restock pitch routes through the shared HITL gate; rejection ends without notifying
- [ ] On approval, a `RESTOCK_OPPORTUNITY` CRM event is emitted with store + restock_days
- [ ] `graph_type="retention"` resumes correctly via the approve/reject endpoints
- [ ] `build_retention_graph` exported from the registry; existing tests stay green
