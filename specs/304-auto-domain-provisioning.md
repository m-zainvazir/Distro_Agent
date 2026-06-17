# Spec: P0-4 — Automated Domain Provisioning (Layer 20)

## Overview
Blueprint Layer 20's "Domain Rotation & Deliverability Shield" autonomously **purchases, configures
(SPF/DKIM/DMARC), and warms up** secondary sending domains so cold outreach never risks the brand's primary
domain. Today `app/services/domain_service.py` implements only the **warm-up ramp** (day 1→14, 10→100/day) and
bounce-rate auto-pause. This spec adds the missing front half: register a secondary domain and configure DNS
authentication records via a registrar/DNS API, then hand off to the existing warm-up logic.

## Files to create / modify
| File | Purpose |
|---|---|
| `app/tools/domain_registrar.py` | Async client for a registrar/DNS API (Namecheap or Cloudflare) — purchase domain, set DNS records |
| `app/services/domain_service.py` (modify) | `provision_sending_domain(tenant_id, brand_name)` → register + configure SPF/DKIM/DMARC → create `SendingDomain` in warm-up state |
| `app/models/sending_domain.py` (modify) | Add `provisioning_status`, `dns_verified_at` fields |
| `alembic/versions/<rev>_domain_provisioning.py` | Migration for new fields |
| `app/core/config.py` (modify) | Registrar API creds (from env), default domain templates |
| `tests/services/test_domain_provisioning.py` | Mocked registrar — record creation + state transitions |

## Behavior
1. Generate a candidate secondary domain from templates (e.g. `try{brand}.com`, `{brand}wholesale.com`).
2. Call the registrar API to purchase (or verify ownership of) the domain.
3. Set DNS records: **SPF** (`v=spf1 ...`), **DKIM** (public key from the ESP/SendGrid), **DMARC** (`p=none` → ramp to `quarantine`).
4. Poll for DNS propagation; on verify, set `dns_verified_at` and create a `SendingDomain` row in warm-up day-1 state.
5. Existing warm-up ramp + bounce-pause logic takes over from there — unchanged.

## Critical Rules
- NEVER touch or send from the brand's **primary** domain (matches existing email_service guard).
- Registrar/ESP credentials come from env via `settings` — NEVER hardcoded.
- Use real async `httpx` with retry/backoff (mirror existing service-client patterns).
- DMARC starts at `p=none`; only ramp policy after warm-up proves clean.
- Every query filters by `tenant_id`; type hints everywhere; `make lint` clean.

## Acceptance Criteria
- [ ] `provision_sending_domain` registers a domain and writes SPF/DKIM/DMARC records (registrar mocked in tests)
- [ ] A verified domain creates a `SendingDomain` row in warm-up day-1 state, handing off to existing ramp logic
- [ ] DMARC initialized at `p=none`
- [ ] Primary domain is never used for sending (guard preserved)
- [ ] All credentials sourced from `settings`/env, no hardcoding
- [ ] Provisioning + state-transition tests pass; 264 existing tests stay green
