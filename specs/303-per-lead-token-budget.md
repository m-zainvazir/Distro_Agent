# Spec: P0-3 — Per-Lead Token Budget (Layers 14 & 16)

## Overview
Blueprint Layers 14 & 16 require a **strict algorithmic token budget per lead** to protect the 85%+ DFY margin,
and reserve expensive (future paid vision) calls for top-tier leads (score > 8). Today there are per-run cost
guards (`$0.10/agent`) but no cumulative budget across the multi-agent journey of a single lead. Add a
lightweight cost ledger keyed by lead, checked before each LLM call, that escalates to the founder (or skips the
expensive path) when the budget is exhausted.

## Files to create / modify
| File | Purpose |
|---|---|
| `app/core/budget.py` | `LeadBudget` helper: track spend per lead, `check_and_reserve(cost) -> bool` |
| `app/core/config.py` (modify) | `MAX_TOKENS_PER_LEAD`, `MAX_COST_PER_LEAD_USD`, `VISION_MIN_SCORE` constants |
| `app/tools/vision_analyzer.py` (modify) | Record token usage to the lead ledger after each call |
| `app/agents/*` (modify call sites) | Before an LLM call, consult `LeadBudget`; if exhausted → skip/escalate |
| `tests/core/test_budget.py` | Budget exhaustion + reservation logic |

## Data Model
`LeadBudget` (in-memory per request/graph run, optionally Redis-backed later):
`lead_id, tokens_spent, cost_spent_usd, max_tokens, max_cost_usd`.

## Behavior
- Each LLM-calling node calls `budget.check_and_reserve(estimated_cost)` first.
  - Within budget → proceed, then record actual usage from `response.usage`.
  - Over budget → skip the expensive path (use cheaper/cached result) and log `lead_budget_exhausted`.
- **Tier gate:** any expensive/vision path is only entered when `lead_score > VISION_MIN_SCORE` (default 8.0)
  AND budget remains — directly encoding the Layer 16 rule.
- Budget values come from `settings`; never hardcoded.

## Critical Rules
- NEVER exceed `MAX_COST_PER_LEAD_USD` for a single lead's full agent journey.
- Expensive paths gated by BOTH score threshold AND remaining budget.
- Use the logger (`app/core/logging.py`) — never `print()`.
- Type hints on every function; `make lint` clean.

## Acceptance Criteria
- [ ] `LeadBudget.check_and_reserve` returns False once cumulative cost would exceed the cap
- [ ] Token usage recorded from real `response.usage` after each call
- [ ] Vision/expensive path entered only when `lead_score > VISION_MIN_SCORE` AND budget remains
- [ ] Budget exhaustion downgrades gracefully (no crash) and logs the event
- [ ] All thresholds read from `settings`, not hardcoded
- [ ] Tests prove exhaustion + tier-gating; 264 existing tests stay green
