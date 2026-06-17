# Spec: P0-2 — KPI / Metrics Surface (Layer 13)

## Overview
Blueprint Layer 13 calls for distribution KPIs (reply rate, booking rate, conversion velocity, CAC, campaign
ROI). Today cost/tokens are logged per-call (`groq_token_usage`) but never aggregated. Build a metrics service
that aggregates from existing tables and exposes them two ways: a JSON endpoint and a **WhatsApp digest** that
reuses the existing calibration-summary send path (`app/services/whatsapp_service.py` + the
`app/tasks/calibration_task.py` beat pattern).

## Files to create / modify
| File | Purpose |
|---|---|
| `app/services/metrics_service.py` | `compute_tenant_kpis(tenant_id, lookback_days) -> KpiSummary` |
| `app/schemas/metrics.py` | `KpiSummary` Pydantic v2 model |
| `app/api/v1/metrics.py` | `GET /api/v1/metrics/kpis` (JWT, tenant-scoped) |
| `app/tasks/metrics_task.py` | Daily beat job → WhatsApp KPI digest (reuse calibration send path) |
| `app/api/v1/router.py` (modify) | Register the metrics router |
| `tests/services/test_metrics.py` | Aggregation correctness + tenant isolation |

## Data sources (existing tables — no new schema)
- `outreach_emails` (status, outcome, tenant_id, timestamps) → emails sent, reply rate, positive-reply rate
- `outreach_campaigns` → campaign-level rollups
- `store_candidates` → leads discovered / qualified counts
- Scheduling events / `MEETING_BOOKED` CRM events → booking rate
- `groq_token_usage` logs / cost guards → token + $ spend per campaign

## KpiSummary fields
`leads_discovered, leads_qualified, emails_sent, reply_rate, positive_reply_rate, meetings_booked,
booking_rate, deals_closed, total_cost_usd, cost_per_lead, lookback_days, generated_at`.

## Behavior
- All aggregation queries filter by `tenant_id` and a `lookback_days` window (default 30).
- `GET /metrics/kpis?lookback_days=30` returns `KpiSummary` for the authenticated tenant only.
- Daily beat task computes per-tenant KPIs and sends a WhatsApp digest via the existing
  `whatsapp_service` send function (same path the calibration summary uses).
- Division-by-zero guarded (0 emails → 0.0 rates, not error).

## Critical Rules
- Read-only over existing tables — no new migrations, no writes.
- Every query filters by `tenant_id` (multi-tenant isolation).
- Reuse `whatsapp_service` + calibration task pattern — do NOT build a new notification mechanism.
- Type hints on every function; `make lint` clean.

## Acceptance Criteria
- [ ] `compute_tenant_kpis` returns correct aggregates against seeded fixture data
- [ ] All rates guarded against division-by-zero
- [ ] `GET /metrics/kpis` is JWT-protected and returns only the caller's tenant data
- [ ] Cross-tenant request cannot see another tenant's KPIs (isolation test)
- [ ] Daily beat task sends a WhatsApp digest reusing the calibration send path
- [ ] Tests cover aggregation + isolation; 264 existing tests stay green
