# DistroAgent — Phase 2 Complete Context

**Date saved:** 2026-06-10  
**Test status:** 149/149 passing  
**Branch:** main  
**Last commits:** `09edefe` Merge PR#2 feature/Phase2B → main

Paste this file at the start of any new session to restore full context.

---

## 1. What DistroAgent Is

A multi-tenant B2B distribution SaaS. A brand founder gives it their website URL; it scouts physical retail stores that match their aesthetic, scores each lead, drafts personalised outreach emails, handles buyer replies, negotiates counter-offers, and books intro calls — all with the founder approving every send via WhatsApp before anything leaves the system.

**Stack:** Python 3.11 · LangGraph StateGraph · FastAPI · PostgreSQL · Qdrant · Redis · Celery  
**LLM:** Groq `llama-3.3-70b-versatile` (free tier) — NOT OpenAI, NOT Anthropic  
**Embeddings:** `sentence-transformers BAAI/bge-small-en-v1.5` (384-dim, local) — NOT OpenAI ada-002  
**Email:** SendGrid via secondary sending domain (never primary brand domain)  
**WhatsApp:** Meta Business API (approval cards + webhooks)  
**Calendar:** Google Calendar OAuth (FreeBusy + event creation with Meet link)  
**Gmail:** Google OAuth (read-only polling for replies)

---

## 2. Project Structure

```
distroagent/
├── app/
│   ├── agents/              # LangGraph agents (one file per agent)
│   │   ├── brand_extractor.py      # Phase 1 — extract brand profile from URL
│   │   ├── scout_agent.py          # Phase 1 — find stores via Google Maps
│   │   ├── analyst_agent.py        # Phase 1 — score store leads
│   │   ├── hitl_gate.py            # Shared HITL: request_human_approval() = interrupt()
│   │   ├── copywriter_agent.py     # Block C — draft + critique loop + HITL
│   │   ├── reply_handler_agent.py  # Block F — classify buyer replies by intent
│   │   ├── negotiator_agent.py     # Block G — rulebook-gated counter-offers + HITL
│   │   └── scheduling_agent.py     # Block H — calendar slots + booking + HITL
│   ├── api/v1/
│   │   ├── auth.py                 # POST /auth/signup, /auth/login → JWT
│   │   ├── brands.py               # POST /brands/extract
│   │   ├── campaigns.py            # POST /campaigns/start, /approve, /reject, /simulate-reply
│   │   ├── scoring.py              # POST /scoring/score-batch
│   │   ├── insights.py             # GET /insights/similar-brands
│   │   ├── webhooks.py             # GET+POST /webhooks/whatsapp (HMAC-verified)
│   │   └── endpoints/discovery.py  # Phase 1 discovery endpoints
│   ├── core/
│   │   ├── config.py               # Settings (pydantic-settings, reads .env)
│   │   ├── checkpointer.py         # AsyncPostgresSaver → MemorySaver fallback
│   │   ├── dependencies.py         # get_current_tenant() JWT → Tenant row
│   │   ├── resume.py               # resume_graph_for_email() → Command(resume=...)
│   │   ├── security.py             # JWT encode/decode
│   │   ├── database.py             # AsyncSessionLocal, get_db
│   │   ├── qdrant.py               # get_qdrant_client() singleton
│   │   └── logging.py             # structlog logger
│   ├── models/
│   │   ├── campaign.py             # Tenant, BrandProfileRecord, StoreCandidate,
│   │   │                           #   OutreachCampaign, OutreachEmail (has tenant_id)
│   │   ├── brand_profile.py        # BrandProfile Pydantic model
│   │   ├── store_candidate.py      # StoreCandidate, ScoredStore, DimensionScore
│   │   ├── outreach.py             # OutreachEmailDraft Pydantic model
│   │   ├── rulebook.py             # WholesaleRulebook (frozen Pydantic, per-tenant)
│   │   ├── sending_domain.py       # SendingDomain SQLAlchemy model
│   │   ├── user.py                 # User model
│   │   └── base.py                 # Base, TenantMixin, TimestampMixin
│   ├── services/
│   │   ├── brand_service.py        # extract_brand(), save_brand_profile_record()
│   │   ├── analyst_service.py      # score_stores() — calls all scorer tools
│   │   ├── scout_service.py        # scout_stores() — calls scout agent
│   │   ├── email_service.py        # send_outreach_email() — asserts outcome=='approved'
│   │   ├── domain_service.py       # get_active_domain(), warmup ramp, bounce tracking
│   │   ├── gmail_service.py        # fetch_new_replies() — OAuth, no passwords
│   │   ├── calendar_service.py     # get_free_slots(), create_event() with Meet link
│   │   ├── whatsapp_service.py     # send_approval_card(), send_deal_alert(),
│   │   │                           #   process_incoming_message()
│   │   ├── similarity_service.py   # find_similar_brands() (anonymized), dedup_stores()
│   │   └── campaign_service.py     # register_pending_approval(), get_pending_approval()
│   ├── tasks/
│   │   ├── email_tasks.py          # Celery beat every 15min: send approved emails
│   │   └── reply_tasks.py          # Celery beat hourly: poll Gmail + follow-up sequencer
│   ├── tools/                      # Scorer tools (category, price, engagement, wholesale,
│   │   │                           #   vision, embedding, catalog_fetcher, google_maps…)
│   │   └── category_scorer.py      # Embedding path + curated keyword-map fallback
│   └── workflows/
│       ├── phase1_workflow.py      # brand_extractor → scout → analyst → report
│       ├── phase2_workflow.py      # Master: copywriter→email→reply→negotiate/schedule
│       └── registry.py             # AGENT_REGISTRY dict
├── tests/                          # Mirror of app/ — 149 tests, all passing
│   ├── agents/                     # test_copywriter_agent, negotiator, scheduling,
│   │   │                           #   reply_handler, brand_extractor, scout, analyst
│   ├── services/                   # test_email_service, whatsapp, similarity
│   ├── workflows/                  # test_phase1_workflow, test_phase2_workflow
│   ├── api/                        # test_auth
│   └── tools/                      # test_category_scorer
├── specs/                          # Feature specs (read before modifying a block)
│   ├── phase2-master-workflow.md
│   ├── 205EmailDelivery.md (Block E)
│   ├── 206ReplyHandlerAgent.md (Block F)
│   ├── 207NegotiatorAgent.md (Block G)
│   ├── 208SchedulingAgent.md (Block H)
│   ├── 208QdrantSimilarity.md (Block I)
│   └── 209Productiondeploy.md (Block J)
├── .claude/
│   ├── commands/                   # /verify-hitl, /tenant-audit, /review-agent,
│   │                               #   /build-block, /tenant-audit, /run-spec
│   └── agents/                     # copywriter-agent.md, negotiator-agent.md,
│                                   #   scout-agent.md
├── Dockerfile                      # python:3.11-slim, installs reqs + playwright
├── docker-compose.yml              # api + worker + beat + postgres + redis + qdrant
├── fly.toml                        # Fly.io deploy config (app=distroagent, iad)
├── Procfile                        # web / worker (prefork,4) / beat
├── .github/workflows/ci.yml        # ruff + mypy + pytest on every push/PR
├── Makefile                        # dev / test / test-phase2 / lint / db-migrate
└── .env.example                    # All required env vars (copy to .env, fill secrets)
```

---

## 3. Environment Variables (copy .env.example → .env)

```
# Required
GROQ_API_KEY=gsk_...
SECRET_KEY=<random 32 chars>
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/distroagent
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333

# WhatsApp (Meta Business API)
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_APP_SECRET=        # used to verify X-Hub-Signature-256
WHATSAPP_VERIFY_TOKEN=      # set in Meta webhook config
WHATSAPP_FOUNDER_PHONE=     # e.g. +12125551234

# Email (SendGrid)
SENDGRID_API_KEY=

# Gmail OAuth (read-only, to poll buyer replies)
GMAIL_OAUTH_CLIENT_ID=
GMAIL_OAUTH_CLIENT_SECRET=
GMAIL_OAUTH_REFRESH_TOKEN=

# Google Calendar OAuth (read/write for meeting booking)
GOOGLE_CALENDAR_OAUTH_CLIENT_ID=
GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET=
GOOGLE_CALENDAR_OAUTH_REFRESH_TOKEN=

# Optional
GOOGLE_MAPS_API_KEY=
QDRANT_API_KEY=             # only for Qdrant Cloud
LANGSMITH_API_KEY=          # LangSmith tracing
LANGSMITH_PROJECT=distroagent
CORS_ORIGINS=*              # production: https://yourdomain.vercel.app
ETSY_API_KEY=               # Phase 1 Etsy scraping
```

---

## 4. Common Commands

```bash
make dev              # uvicorn hot-reload on :8000
make test             # pytest tests/ (149 tests)
make test-phase2      # pytest for Phase 2 blocks only
make lint             # ruff + mypy
make db-migrate       # alembic upgrade head

# Docker (local parity)
docker-compose up -d  # starts postgres + redis + qdrant + api + worker + beat

# Deploy
fly deploy            # uses Dockerfile
fly secrets set KEY=val ...
fly logs
```

---

## 5. Phase 2 Block-by-Block Reference

### Block C — Copywriter Agent (`app/agents/copywriter_agent.py`)

**State:** `CopywriterState` TypedDict — store, brand_profile, founder_name, email_tone, tenant_id, campaign_id, store_db_id, draft_subject_a/b, draft_body, personalization_score, critique_notes, revision_count, approved, final_email, token_usage, cost_usd

**Graph:** `draft → critique → route_revision → hitl_approval → finalize`  
- `route_revision` loops back to draft if `score < 7.0 AND revision_count < 2 AND cost < $0.10`
- `hitl_approval_node`: saves draft to DB, sends WhatsApp approval card, calls `interrupt()`
- `finalize_node`: sets `final_email` (only if `approved=True`)

**Entry point:** `build_copywriter_graph(checkpointer=...)` — used by `phase2_workflow.invoke_copywriter_node`  
**Cost guard:** `_MAX_DRAFT_COST_USD = 0.10` per email run

---

### Block D — HITL Gate + WhatsApp (`app/agents/hitl_gate.py`, `app/services/whatsapp_service.py`, `app/core/resume.py`)

**Gate:** `request_human_approval(payload)` = `interrupt(payload)` — one line, used by all three agents  
**Approval flow:**
1. Agent node calls `send_approval_card(phone, preview, email_id)` → WhatsApp button card arrives
2. Founder taps Approve/Reject on phone
3. Meta sends POST to `/api/v1/webhooks/whatsapp` (signature-verified with HMAC-SHA256)
4. `process_incoming_message()` reads button ID `approve:<email_id>` or `reject:<email_id>`
5. `resume_graph_for_email(email_id, approved=True/False)` → looks up `{thread_id, graph_type}` in `campaign_service._pending_approvals` → builds correct graph → `Command(resume=approved)` → graph continues

**Pending approvals registry:** In-memory dict in `campaign_service._pending_approvals`. Keyed by `email_id`. Contains `{thread_id, store_name, graph_type, tenant_id}`. Production must keep this in Redis or Postgres for multi-worker resilience.

---

### Block E — Email Delivery (`app/services/email_service.py`, `app/tasks/email_tasks.py`)

**Hard guard:** `assert email.outcome == 'approved'` — line 68 of email_service.py — NO email sends without this  
**Send path:** `phase2_workflow._dispatch_draft()` creates `OutreachEmail(outcome='approved')` → `send_outreach_email()` → SendGrid → `outcome='sent'`  
**Celery fallback:** `send_approved_emails_task` every 15 min picks up any emails stuck at `outcome='approved'`  
**Domain warmup:** `daily_send_limit(domain)` = linear ramp day 1→14 (10→100 emails/day). Bounce rate > 5% auto-pauses the domain.  
**Important:** Emails send FROM the tenant's secondary domain (e.g. `trybrandname.com`), NEVER their primary domain.

---

### Block F — Reply Handler + Follow-up Sequencer (`app/agents/reply_handler_agent.py`, `app/tasks/reply_tasks.py`)

**Intents (keyword-scoring, no LLM):**
- `INTERESTED` → `send_catalog` (catalog email queued for HITL)
- `OBJECTION` → `route_to_negotiator` + NegotiatorAgent fires
- `NOT_INTERESTED` → `mark_lead_lost`
- `MEETING_REQUEST` → `route_to_scheduling` + SchedulingAgent fires
- `NO_REPLY` — handled by follow-up sequencer (time-based, not classifier)

**Celery task:** `check_replies_task()` hourly — polls Gmail, classifies replies, runs follow-up sequencer  
**Follow-up sequencer:** stale email (5+ days, no reply) → `outcome='pending_approval'`, `follow_up_count++`, registered in `campaign_service` for HITL. After 2 follow-ups → `outcome='ignored'` (dormant).  
**tenant_id propagation:** Resolved via `OutreachEmail.tenant_id` (direct column, added during Phase 2).

---

### Block G — Negotiator Agent (`app/agents/negotiator_agent.py`, `app/models/rulebook.py`)

**Rulebook:** `WholesaleRulebook` (frozen Pydantic) — min_order_quantity=12, wholesale_discount_max_pct=50.0, net_payment_days_max=30, free_shipping_threshold=500.0, non_negotiables=list[str]  
**Graph:** `parse_objection → check_rulebook → route → [draft_counter → hitl_approval → finalize | escalate → END]`  
**Critical invariants:**
- `_check_within_rulebook()` is deterministic (no LLM) — checks non-negotiables first
- Out-of-rulebook → `escalate_node` ALWAYS. Never auto-counter outside limits.
- Every counter routes through `hitl_approval_node` interrupt — no exceptions.

**State key fields:** objection_text, buyer_email, tenant_id, rulebook, objection_type, within_rulebook, counter_offer_body, approved, final_counter, token_usage, cost_usd, graph_thread_id  
**Cost guard:** `_MAX_COUNTER_COST_USD = 0.10`  
**Objection types:** PRICE / MOQ / SHIPPING / NET_TERMS / OTHER

---

### Block H — Scheduling Agent (`app/agents/scheduling_agent.py`, `app/services/calendar_service.py`)

**Guardrail (CRITICAL):** Only fires when `lead_score > 8.0 OR explicit_request == True`  
**Graph:** `guardrail → [END | fetch_availability → propose_slots[HITL] → [END | wait_for_selection[interrupt] → book → confirm → notify → END]]`

**State key fields:** lead_score, explicit_request, buyer_email, buyer_name, store_name, tenant_id, available_slots, selected_slot, proposal_body, approved, event_id, meet_link, routing_action, graph_thread_id

**Calendar service:**
- `get_free_slots(days_ahead=7, slot_duration_mins=30, max_slots=10)` → calls FreeBusy API, generates 9am–5pm UTC weekday windows
- `create_event(slot, attendee_emails, title)` → `conferenceDataVersion=1` → Google Meet link extracted from `conferenceData.entryPoints`

---

### Block I — Qdrant Similarity + Store Dedup (`app/services/similarity_service.py`)

**`find_similar_brands(tenant_id, brand_id, k=5) → list[SimilarBrand]`**
- Cosine search on `brand_embeddings` Qdrant collection using `client.query_points()`
- Excludes self by matching `payload["brand_id"] == str(brand_id)`
- Returns `SimilarBrand` — deliberately omits: brand_name, tenant_id, store_list, contact, email, phone, address, brand_url

**`dedup_stores(tenant_id, candidates, db) → list[StoreCandidate]`**
- Queries `StoreCandidate.google_place_id WHERE tenant_id = ?`
- Filters out candidates already in DB for this tenant
- Called from `analyst_service.score_stores()` before scoring

**API endpoint:** `GET /api/v1/insights/similar-brands?brand_id=<uuid>&k=5` (requires JWT)

---

### Master Phase 2 Workflow (`app/workflows/phase2_workflow.py`)

**State:** `Phase2State` TypedDict — tenant_id, brand_profile, store, founder_name, email_tone, campaign_id, store_db_id, buyer_email, buyer_name, approved_email, copywriter_thread_id, outreach_email_id, email_sent, reply_text, sender_email, gmail_thread_id, reply_intent, negotiation_thread_id, scheduling_thread_id, meet_link, phase, follow_up_count, errors

**Graph flow:**
```
invoke_copywriter [Block C, HITL forwarded]
    ↓ approved_email set
dispatch_email [creates OutreachEmail record, sends via SendGrid]
    ↓
await_reply [interrupt() — waits for Gmail poller or operator resume]
    ↓
classify_reply [keyword scorer, no LLM]
    ├─ INTERESTED       → handle_interested → phase=won → END
    ├─ OBJECTION        → invoke_negotiator [Block G, HITL forwarded] → END
    ├─ NOT_INTERESTED   → mark_lost → phase=lost → END
    ├─ MEETING_REQUEST  → invoke_scheduler [Block H, HITL forwarded] → END
    └─ (empty reply)    → handle_no_reply → phase=dormant → END
invoke_copywriter fails → draft_rejected → END
```

**HITL forwarding pattern** (used by all three sub-agent nodes):
```python
result = await graph.ainvoke(initial, config=config)
while "__interrupt__" in result:
    approved = interrupt({"type": "..._hitl", **result["__interrupt__"][0].value})
    result = await graph.ainvoke(Command(resume=approved), config=config)
```

**Phase constants:** PHASE_DRAFTING, PHASE_EMAIL_SENT, PHASE_AWAITING_REPLY, PHASE_WON, PHASE_LOST, PHASE_DORMANT, PHASE_NEGOTIATING, PHASE_SCHEDULING, PHASE_DRAFT_REJECTED, PHASE_DISPATCH_FAILED

**Module-level patchable helper:** `_dispatch_draft(approved, buyer_email, campaign_id, store_db_id) → str` — used in tests via `patch("app.workflows.phase2_workflow._dispatch_draft", ...)`

---

## 6. Data Model Key Points

**`OutreachEmail`** (campaign.py) — has direct `tenant_id` column (FK to tenants, nullable). Added in Phase 2 to avoid needing campaign JOINs in Celery tasks.

**`WholesaleRulebook`** — frozen Pydantic model, not a DB model. Per-invocation, not persisted. Loaded from defaults or tenant config at negotiation time.

**`SendingDomain`** — per-tenant secondary domain. Tracks: domain, tenant_id, is_active, paused, warmup_day, emails_sent_today, last_send_date, send_count, bounce_count.

**Multi-tenancy enforcement:**
- Every API endpoint uses `get_current_tenant` FastAPI dependency
- Every DB query on tenant-owned data filters by `tenant_id`
- `SimilarBrand` response model omits all identifying fields by design

---

## 7. Security Architecture

**Authentication:** JWT Bearer tokens. `SECRET_KEY` env var. Tokens contain `tenant_id` claim.

**WhatsApp webhook:** `X-Hub-Signature-256` HMAC-SHA256 verified against `WHATSAPP_APP_SECRET` before any payload processing. Invalid signatures → HTTP 403.

**Email send guard:** `assert email.outcome == 'approved'` in `send_outreach_email()`. Hard crash if bypassed.

**HITL invariant:** Every outbound message (email + WhatsApp notification) is downstream of at least one `interrupt()` call. Verified by `/verify-hitl` audit — no unsafe send paths.

**Cross-tenant HITL gap (pre-launch fix needed):** `POST /campaigns/{email_id}/approve` authenticates the caller but does NOT verify the `email_id` belongs to that tenant. Fix: add ownership check in `approve_email` and `reject_email` before multi-tenant go-live.

---

## 8. Checkpointer + State Persistence

`app/core/checkpointer.py` — `get_checkpointer()`:
1. Tries `AsyncPostgresSaver` from `settings.database_url` (strips `+asyncpg` → plain psycopg DSN)
2. Falls back to singleton `MemorySaver` if libpq unavailable

**Production requirement:** `libpq` + `psycopg` must be installed in the Docker image for `AsyncPostgresSaver`. The Dockerfile installs `libpq-dev` at OS level. Verify `psycopg[c]` or `psycopg2-binary` is in `requirements.txt`.

**`MemorySaver` in production = data loss on restart.** All pending HITL approvals lost. Don't use in production.

---

## 9. Celery Configuration (`app/celery_app.py`)

- `worker_pool = "solo"` on Windows, `"prefork"` on Linux (production)
- `beat_schedule`:
  - `send-approved-emails`: `email.send_approved` every 15 min (900s)
  - `check-replies`: `replies.check_replies` every hour (3600s)
- LangSmith env vars set at module level (so workers get tracing, not just web process)
- `task_serializer = "json"`, `result_serializer = "json"`, `accept_content = ["json"]`
- Includes: `app.tasks.email_tasks`, `app.tasks.reply_tasks`

---

## 10. Test Coverage Summary

| File | Tests | What's covered |
|---|---|---|
| test_brand_extractor.py | 9 | Brand extraction, platform detection, error paths |
| test_scout_agent.py | varies | Store scouting via Google Maps |
| test_analyst_agent.py | varies | Lead scoring pipeline |
| test_category_scorer.py | 10 | Embedding path + curated fallback |
| test_copywriter_agent.py | 17 | Draft, critique, revision loop, HITL, cost guard |
| test_negotiator.py | 17 | Objection parsing, rulebook checks, HITL, cost guard |
| test_scheduling.py | 13 | Guardrail, slot proposal, booking, HITL, error handling |
| test_reply_handler.py | 13 | All 5 intents, graph routing, follow-up states |
| test_email_service.py | 12 | Send guard, domain selection, daily cap, bounce |
| test_whatsapp.py | 8 | Approval card, deal alert, webhook processing |
| test_similarity.py | 9 | Cosine search, self-exclusion, PII omission, dedup |
| test_phase1_workflow.py | varies | Phase 1 chain |
| test_phase2_workflow.py | 22 | All intent branches, HITL interrupt, tenant isolation |
| test_auth.py | 9 | JWT issue, protected endpoints, 401 paths |
| **Total** | **149** | **All passing** |

---

## 11. Release Checklist Status

```
Foundation
☑  Block A — Auth & multi-tenancy live, every endpoint protected
☑  Block A — /tenant-audit passes, zero unfiltered queries
☑  Block B — Category scorer fixed (embedding + curated map fallback)
☑  Block B — Brand name extraction fixed

Outreach Engine
☑  Block C — Copywriter agent with self-critique loop
☑  Block C — HITL gate pauses graph, /verify-hitl passes
☑  Block D — WhatsApp approval cards + webhook resume working
☑  Block E — Email delivery with status=='approved' guard
☑  Block E — Secondary domain warming configured
☑  Block F — Reply handler classifies all 5 intents
☑  Block F — Follow-up sequencer (#1 at 5d, #2 at 10d) via HITL
☑  Block G — Negotiator drafts within rulebook, escalates outside
☑  Block H — Scheduling agent with calendar guardrail (>8.0)

Intelligence & Ship
☑  Block I — Qdrant similarity search + store dedup active
☑  Block I — Cross-tenant data anonymized (no PII leak)
☐  Block J — Deployed to production, /health returns 200       ← run: fly deploy
☐  Block J — All secrets rotated and in platform manager        ← manual: each provider
☑  Block J — GitHub Actions CI passing, blocks bad merges
☑  Master workflow wired, /verify-hitl + /tenant-audit pass
☑  End-to-end test: scored store → approved email → reply → meeting booked

Score: 19/21 automated ✅  |  2 manual steps remaining ☐
```

---

## 12. Known Issues & Pre-Launch Fix List

### Must fix before multi-tenant launch
1. **Cross-tenant HITL approval** — `POST /campaigns/{email_id}/approve` doesn't verify `email_id` belongs to calling tenant. Fix: join `_pending_approvals[email_id]["tenant_id"]` against `str(current_tenant.id)` in `campaigns.py` approve/reject endpoints.

### Should fix soon
2. **`campaign_service._pending_approvals` is in-memory** — lost on worker restart, not shared across multiple workers. Fix: migrate to Redis hash or a `pending_approvals` Postgres table.

3. **`OutreachEmail.tenant_id` is nullable** — should be non-nullable FK. Requires a migration with data backfill (set tenant_id from campaign.tenant_id for existing rows).

4. **`SchedulingState.graph_thread_id`** — field exists in the TypedDict but is not in the test `_initial_state()` helper for all tests. Tests pass because TypedDict doesn't enforce at runtime, but the field IS used in `propose_slots_node` at `state.get("graph_thread_id", "unknown")`. No runtime error, but cleaner if always set. Fixed in `phase2_workflow.py:invoke_scheduler_node`.

### Architectural notes (not urgent)
5. **Celery global queries** — `email_tasks` and `reply_tasks` query all tenants' emails in one batch (no per-tenant scoping in the query itself). Safe because tenant context is derived per-record, but long-term add `tenant_id` filter to all Celery queries.

6. **`MemorySaver` fallback warning** — in production without `libpq`, graph state is in-memory only. Worker restart = lost HITL state. Ensure `libpq` is installed.

---

## 13. What Phase 3 Likely Involves

Based on the pattern so far, Phase 3 will probably cover:
- Frontend UI for Phase 2 features (campaign dashboard, HITL approval UI, reply inbox, negotiation status, meeting calendar)
- Analytics: conversion funnel (scored → contacted → replied → negotiated → booked → won)
- Multi-campaign management (launch outreach across multiple cities/verticals simultaneously)
- CRM-style store status tracking
- Webhook integrations (Calendly, Slack notifications, etc.)
- Billing / plan limits

---

## 14. How to Resume a New Session

1. Paste this entire file into the new chat
2. Run `make test` to verify green baseline: `149 passed`
3. Check `git status` for any uncommitted changes
4. Pick up from the two remaining manual steps (Block J deploy + secrets) or start Phase 3

**Key rule for new sessions:** NEVER use `print()` — use `from app.core.logging import logger`. ALWAYS add type hints. ALWAYS check existing patterns before creating new files. NEVER hardcode API keys.
