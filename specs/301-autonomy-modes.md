# Spec: P0-1 — Autonomy Modes (Assist / Semi-Auto / Full-Auto)

## Overview
Blueprint Layer 8 promises **configurable autonomy modes** per founder. The HITL plumbing already exists
(`request_human_approval()` = `interrupt()` in `app/agents/hitl_gate.py`, shared by all outreach agents), so this
is mostly a gating flag, not new machinery. Add a per-tenant `autonomy_mode` that controls how strict the HITL
gate is, with **unbypassable** gates for final pricing / contracts regardless of mode.

| Mode | Behavior |
|---|---|
| `assist` | AI drafts only — every outbound action requires explicit founder approval (current default behavior) |
| `semi_auto` | AI sends routine outreach (copywriter emails) autonomously; **deal-level** actions (counter-offers, scheduling, invoices) still require approval |
| `full_auto` | Autonomous within micro-thresholds; only **unbypassable** gates (final pricing, contracts) interrupt |

## Files to create / modify
| File | Purpose |
|---|---|
| `app/models/campaign.py` (modify `Tenant`) | Add `autonomy_mode` column (enum, default `assist`) |
| `alembic/versions/<rev>_add_autonomy_mode.py` | Migration adding the column with `assist` backfill |
| `app/agents/hitl_gate.py` (modify) | `request_human_approval()` checks mode + action-class; skips `interrupt()` when the mode permits AND the action is not unbypassable |
| `app/core/config.py` (modify) | `UNBYPASSABLE_ACTIONS` constant (final pricing, contracts) |
| `app/api/v1/campaigns.py` or `auth.py` (modify) | `PATCH /api/v1/tenant/autonomy-mode` to set the mode |
| `tests/agents/test_hitl_gate.py` (modify/create) | Mode × action-class gating matrix |

## Data Model
`Tenant.autonomy_mode: str` — enum `{assist, semi_auto, full_auto}`, default `assist`, non-null.

## Behavior
- `request_human_approval(action_class, ...)` gains an `action_class` arg: `routine_outreach | deal | unbypassable`.
- Gate decision table:
  - `unbypassable` → ALWAYS `interrupt()` (every mode)
  - `deal` → `interrupt()` unless mode == `full_auto`
  - `routine_outreach` → `interrupt()` only when mode == `assist`
- Default for any existing call without `action_class` is `unbypassable` (fail-safe — never silently auto-send).

## Critical Rules
- Final pricing and contract approval are ALWAYS gated — no mode can bypass them.
- Default mode for every existing + new tenant is `assist` (no behavior change until explicitly opted in).
- Every query touching `autonomy_mode` filters by `tenant_id`.
- Add type hints to every changed function; `make lint` clean.

## Acceptance Criteria
- [x] `Tenant.autonomy_mode` column + Alembic migration (`e5f6a7b8c9d0`, `server_default="assist"`)
- [x] `request_human_approval` gates by (mode × action_class) per the table above (`should_request_approval`)
- [x] Unbypassable actions interrupt in ALL modes (proven by test)
- [x] `full_auto` skips deal-level interrupts but NOT unbypassable ones
- [x] `assist` preserves today's behavior exactly (regression test + default-call test)
- [x] `PATCH /tenant/autonomy-mode` updates the mode for the authenticated tenant only
- [x] Gating matrix tests pass; existing tests stay green (**274 passed**, was 264)

## Implementation notes
- Gate logic lives in `app/agents/hitl_gate.py` (mode/action constants + `should_request_approval` + updated
  `request_human_approval`). Runtime mode lookup in `app/services/tenant_service.py::get_autonomy_mode`
  (fail-safe → `assist`). Wired into copywriter (`ROUTINE_OUTREACH`), negotiator + scheduling (`DEAL`).
  Endpoint in `app/api/v1/tenant.py`, registered in `app/api/v1/router.py`.
- Invoice/contract finalization remains gated by the separate `require_admin_approval` governance flow — that
  is the unbypassable layer; negotiator counter-offers are classed `DEAL` (a negotiation step, not final pricing).
- Migration `e5f6a7b8c9d0` not yet applied to any DB — run `make db-migrate` (or `alembic upgrade head`).
