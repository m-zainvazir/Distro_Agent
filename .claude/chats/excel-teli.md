# DistroAgent — Blueprint vs. Reality (Gap Analysis & Build Plan)

> **Generated:** 2026-06-17 · **Branch:** `main` · **Tests:** 264/264 passing
> **Sources reconciled:** `Distro Agent Blueprint - Micro SAAS and AI Product.xlsx` (23 moat layers + 4-phase
> roadmap + Inputs/Outputs) × `feature-checklist.md` (what's actually built) × live codebase (Grep/Glob verified).

This document reconciles your **master blueprint** (the full 10/10 vision) against **what is actually built and
tested today**, scores how far each layer is achieved, says what's left and how to close it, and adds my own
suggestions.

### Legend
| Symbol | Meaning |
|---|---|
| ✅ | Built & verified |
| 🟡 | Partial — core exists, blueprint scope not fully met |
| 🔴 | Not built |
| ⏭️ | Deliberately deferred to **Phase 5+ / Future** (agency-side infra) |

### Two deliberate substitutions (not gaps)
1. **Orchestration:** Blueprint says **n8n**; build uses **LangGraph StateGraph**. Same intent (multi-agent
   swarm orchestration), code-native implementation. Treated as equivalent, *not* a gap.
2. **LLM:** Blueprint names **Claude / GPT-4o**; build uses **free-tier Groq `llama-3.3-70b-versatile`** +
   local `sentence-transformers` embeddings. This is your standing free-tier preference. Where the blueprint's
   paid capability genuinely changes the outcome (true multimodal vision), it's flagged as an **optional** paid
   upgrade — **all "how to close" recommendations lead with the free path first.**

---

## 1. Product Scope (one page — so this doc stands alone)

**Tagline:** *Your autonomous intelligence layer from D2C to the retail shelf.*

**Problem:** The "Wholesale Cold Start" bottleneck — the heavy manual effort of discovering, vetting, and
pitching retail stores that match a brand's aesthetic, values, and pricing.

**Solution:** A *Zero-Config Distribution OS*. A D2C founder pastes one Shopify/Etsy/brand URL; a horizontal,
multi-agent AI swarm runs the whole distribution pipeline — discover → score → personalize outreach → handle
replies → negotiate → book calls → invoice → sync to CRM — with the founder approving every outbound action
via WhatsApp (HITL). Strictly **headless / "no-dashboard"**, multi-tenant, DFY (done-for-you) service model
targeting 85%+ gross margin.

**The 4-phase arc:**

| Phase | Codename | Theme |
|---|---|---|
| 1 | **The Eyes** | Discovery, vibe-match intelligence, the verticalized "wedge" report, frontend entry |
| 2 | **The Voice** | Autonomous outreach, scheduling, auth, domains, WhatsApp control plane |
| 3 | **The Brain** | Learning/feedback, governance, negotiation, admin/strategy layer |
| 4 | **The Hands** | Stripe billing, inventory, unit economics, CRM sync, restock/retention |

---

## 2. Layer-by-Layer Scorecard (Core Product — Blueprint Layers 1–21)

> Agency-side Layers 9 & 22 are scored ⏭️ here and detailed in **§8 Phase 5+**.

| # | Blueprint Layer | Status | What's built | What's missing | How to close (free-tier-first) |
|---|---|:---:|---|---|---|
| **1** | Visual Vibe-Match Intelligence | 🟡 | Real 384-dim local embeddings; color-palette extraction (ColorThief); vibe score (35% weight) | **True multimodal vision** — `vision_analyzer.py` is a Groq *text* call despite its name; storefront imagery never actually "seen" | Keep text-approximation (free, works). *Optional paid:* swap in a vision model (Groq Llama-Vision / Claude vision) **only** for top-tier leads (score >8) to protect margin |
| **2** | MCP Retail Discovery Layer | 🟡 | Google Maps Places (New) live: text search + details, chain filtering, rate-limit retry | No custom **MCP servers**; no Instagram scraper; no digital-B2B signal ingestion; no "vector-based retail graph" | Wrap Maps calls behind a thin MCP-style tool interface (free); add Instagram/B2B enrichment later as separate tools |
| **3** | Lead Scoring Intelligence | ✅ | 5-dimension scorer (category/price/engagement/wholesale/vibe), priority tiers, drives sequencing | — | Maintain; feed richer signals as L2 grows |
| **4** | Data Reality & Quality | 🟡 | Structural fallbacks (Maps reviews when social missing), Pydantic models | No explicit **schema-validation/normalization gate** before scoring; no formal data-quality scoring | Add a lightweight validation node (Pydantic v2 validators) in front of the analyst — free, small effort |
| **5** | Agent Swarm Execution | ✅ | Scout, Analyst, Copywriter, Negotiator, Scheduling, Reply-Handler — all LangGraph, all tested | **"Closer"** = negotiator + invoice (acceptable merge); **Retention agent** missing (see L10) | Build Retention agent (P1) — hooks already exist |
| **6** | Human-Assisted Negotiation | ✅ | `WholesaleRulebook` + deterministic rule check + HITL gate + escalation trigger; PRICE/MOQ/SHIPPING/NET_TERMS | A2A schemas intentionally inactive (per blueprint) | None — matches spec |
| **7** | Learning & Feedback | ✅ | Pearson calibration of vibe-weight vs win/loss; 30-day lookback; anonymized cross-brand memory via Qdrant | — | Maintain |
| **8** | Governance & HITL Control | 🟡 | HMAC-signed approval gates, unbypassable on outbound; calendar guardrail (>8/10); Redis-backed token metadata | **Autonomy modes** (Assist / Semi-Auto / Full-Auto) not formalized as a user-facing toggle | Add a per-tenant `autonomy_mode` field gating HITL strictness — plumbing already exists (P0, small) |
| **9** | Adaptive Strategy Engine | ⏭️ | — | GTM experiment generation, niche discovery, WhatsApp deploy prompts | **Phase 5+** (§8) |
| **10** | Full-Stack Distribution OS | 🟡 | **Stripe invoicing** ✅ (create/send/webhook) | Inventory sync, landed-cost margin calc, credit checks, smart contracts, **Retention/Restock agent** (only a `RESTOCK_OPPORTUNITY` CRM enum exists) | P1: Retention agent (reuse the enum + CRM push). P2: inventory webhooks, margin calc, contracts |
| **11** | WhatsApp Control Plane + CRM Sync | 🟡 | Approval cards / deal alerts; webhook HMAC-verified; CRM sync to **webhook/HubSpot/Salesforce/Google Sheets** | Full **"no-dashboard" conversational ops** (manage business via NL); **Klaviyo** connector | P1: conversational command parsing over WhatsApp (free). Add Klaviyo connector (small) |
| **12** | Adaptive RAG Single-Link Onboarding | 🟡 | Single URL → full brand profile in seconds (Shopify/Etsy/Playwright); `vertical_tag` param flows through analyzer | **Niche-critical data adaptation** (e.g. Leaping Bunny / cruelty-free / ingredients for beauty) not implemented | Extend the analyzer prompt per `vertical_tag` to pull niche fields (free, depends on L19 router) |
| **13** | Metrics & Performance Intelligence | 🟡 | Per-call token/cost logging (`groq_token_usage`); calibration accuracy tracking | No aggregated **KPI surface** (reply rate, booking rate, ROI, CAC) | P0: build a KPI aggregation query + WhatsApp digest (reuse calibration-summary path) |
| **14** | Cost, Scalability & Failure | 🟡 | Per-run cost guards ($0.10/agent), graceful failure (tolerates ≤3 errors), retry/backoff | No **per-campaign / per-lead** budget enforcement; no central cost dashboard | P1: add a per-lead token budget check (ties to L16) |
| **15** | Defensibility & Network Intelligence | 🟡 | Anonymized cross-brand similarity (PII-omitting `SimilarBrand`), proprietary outcome data forming | Network effects nascent (small dataset); no attribute→demographic success model | Compounds with usage — no code action now |
| **16** | Unit Economics & Cost-Optimization | 🟡 | Scoring intends tier-gated expensive paths; free models keep margin high by default | No **hard token budget per lead**; vision-for-top-tier-only not enforced (since vision is text now) | P1: enforce a token budget per lead; gate any future paid vision to score >8 |
| **17** | Verticalized Retail Audit "Wedge" | 🟡 | Free "Top-5 boutique matches" discovery report = the wedge ✅; Next.js entry frontend ✅ | Isolated **vertical subdomains** (e.g. `beauty.distroagent.ai`) not deployed | P1: deploy one vertical subdomain + tag injection (depends on L19) |
| **18** | Multi-Tier Dependency Fallback | 🟡 | Vision→text fallback ✅; per-API retry/backoff ✅ | **Multi-provider LLM failover** (e.g. Groq → alt provider on outage) — single provider today | P1: add a provider-failover wrapper around LLM calls (free: add a second free provider like a backup Groq key / Open-compatible endpoint) |
| **19** | Dynamic Context Router & Multi-Tenant | 🟡 | Multi-tenant isolation ✅ (every query filters `tenant_id`); `vertical_tag` parameter flows into analyzer | No real **Context Router** injecting vertical-specific LLM instructions; no subdomain→backend routing layer | P1: build a Context Router that maps `industry` tag → prompt-injection profile (foundation already there via `vertical_tag`) |
| **20** | Zero-Credential Deliverability & Security | 🟡 | OAuth read-only inbox/calendar (no raw passwords) ✅; domain **warm-up ramp** + bounce-pause ✅ | **Automated domain provisioning** — auto-purchase + SPF/DKIM/DMARC config not implemented (`domain_service.py` is warm-up only) | P0/P1: integrate a registrar/DNS API (Namecheap/Cloudflare) to auto-provision secondary sending domains |
| **21** | Hybrid Input UI (Manual vs Manual/Auto) | 🔴 | — | Dual-mode ingestion ("Type Manually" vs "Auto-Fill via AI"); **async onboarding state machine** prompting one step at a time over WhatsApp | P1: model onboarding as a LangGraph state machine with `interrupt()` per step (reuses existing HITL pattern) |

---

## 3. Roadmap Reconciliation (Blueprint Phases vs Build Phases)

| Blueprint Phase | Build status | Aligned? | Notes |
|---|---|:---:|---|
| **P1 — The Eyes** (discovery, wedge, router, frontend) | ✅ mostly | 🟡 | Discovery + wedge report + frontend done. **Lighter:** no Context Router / vertical subdomains yet |
| **P2 — The Voice** (outreach, scheduling, auth, domains, WhatsApp) | ✅ mostly | 🟡 | Swarm + scheduling + auth + WhatsApp cards done. **Lighter:** no auto domain provisioning; no conversational onboarding |
| **P3 — The Brain** (learning, governance, negotiation, admin) | ✅ core | 🟡 | Calibration + governance + negotiation done (**deeper** than blueprint on calibration). **Missing:** Retool admin desk + strategy engine → Phase 5+ |
| **P4 — The Hands** (Stripe, inventory, unit econ, CRM, restock) | 🟡 | 🟡 | Stripe + CRM sync done. **Lighter:** no inventory/landed-cost/credit/smart-contracts/Retention agent |

**Takeaway:** The build faithfully executed the *intelligence and outreach spine* of all four phases, and went
**deeper** on learning/calibration. It is **lighter** on the "Distribution OS" breadth (inventory, contracts,
retention) and on the **verticalization/onboarding UX** that the blueprint treats as core acquisition moat.

---

## 4. Inputs / Outputs Coverage (Blueprint sheet 2)

**Inputs**

| Blueprint input | Status | Notes |
|---|:---:|---|
| Primary Brand URL (Manual) | ✅ | Core discovery entry |
| WhatsApp Phone Number (Manual) | ✅ | Used for HITL cards |
| Secure Inbox 1-Click OAuth (Manual) | ✅ | Gmail/Calendar OAuth read |
| Ideal Retailer Profile / Vibe Target (Manual/Auto) | 🟡 | Manual works; "Auto-fill via AI" path not built (L21) |
| Wholesale Rulebook & Negotiation Params (Manual/Auto) | 🟡 | `WholesaleRulebook` exists (manual); no Auto-generate |
| Stripe / Financial Connection (Manual/Auto) | ✅ | Stripe wired |
| Interactive Pitch & Deal Approvals (Manual/Auto) | ✅ | HITL approval flow |

**Outputs**

| Blueprint output | Status | Notes |
|---|:---:|---|
| Aesthetic-Matched Prospect List | ✅ | Discovery report |
| Retailer Visual "Vibe" Analysis Reports | 🟡 | Produced, but vibe is text-approximated |
| Hyper-Personalized Pitch Drafts | ✅ | Copywriter agent |
| Wholesale Negotiation Summaries | ✅ | Negotiator output |
| WhatsApp "Action Card" Notifications + Reply Alerts | 🟡 | Cards built; live delivery blocked by expired WhatsApp token (your action) |
| Verified Buyer Contact Database (CRM Sync) | ✅ | CRM sync to 4 destinations |
| Automated Wholesale Invoices & POs (Stripe) | ✅ | Invoices ✅; POs not separately modeled |
| Smart-Contract Agreements | 🔴 | Not built |
| Automated Calendar Meeting Invitations | ✅ | Calendar + Meet link |
| Real-Time Campaign Deliverability Analytics | 🟡 | Logged per-call; no aggregated surface (L13) |
| Autonomous Restock Alerts & LTV Reports | 🔴 | Retention agent not built (L10) |

---

## 5. Prioritized "What's Left" Backlog

Effort: **S** ≈ <1 day · **M** ≈ 2–4 days · **L** ≈ 1–2 weeks. All free-tier-first.

### P0 — High value, close to done (build next)
| Item | Effort | How (reuse existing) |
|---|:---:|---|
| **Autonomy modes** (Assist/Semi/Full) | S | Add per-tenant `autonomy_mode`; gate the existing HITL `interrupt()` calls on it |
| **KPI / metrics surface** (L13) | M | Aggregate from `outreach_emails` + campaign tables; deliver as WhatsApp digest reusing the calibration-summary send path |
| **Per-lead token budget** (L14/L16) | S | Add a budget check alongside existing `$0.10` cost guards |
| **Auto domain provisioning** (L20) | M | Extend `domain_service.py` with a registrar/DNS API (Namecheap/Cloudflare) for purchase + SPF/DKIM/DMARC |

### P1 — Core moat depth
| Item | Effort | How (reuse existing) |
|---|:---:|---|
| **Retention/Restock agent** (L10) | M | New LangGraph agent; emit the **existing** `crm_sync.RESTOCK_OPPORTUNITY` event; HITL via existing gate |
| **Dynamic Context Router + vertical tags** (L19/L12/L17) | M | Foundation exists (`vision_analyzer.vertical_tag`); map `industry` → prompt-injection profile |
| **Vertical subdomain wedge** (`beauty.distroagent.ai`) | M | One Next.js subdomain → tag injection into existing discovery flow |
| **Conversational onboarding state machine** (L21/L11) | L | Model onboarding as LangGraph with `interrupt()` per step (reuses HITL pattern) over WhatsApp interactive buttons |
| **Multi-provider LLM failover** (L18) | S | Wrapper around LLM calls; fall back to a second free endpoint on rate-limit/outage |
| **Klaviyo CRM connector** (L11) | S | Mirror the existing HubSpot/Salesforce connector shape in `crm_sync.py` |

### P2 — Breadth / later
| Item | Effort | Notes |
|---|:---:|---|
| Inventory sync + landed-cost margin (L10) | L | Shopify/Etsy inventory webhooks |
| Smart-contract agreements (L10) | L | Legal + e-sign integration |
| Custom MCP servers + Instagram/B2B signals (L2) | L | Wrap Maps first; add scrapers as compliant tools |
| Credit checks (L10) | M | Third-party API; gated by margin |

---

## 6. Pre-Production TODOs (carried from feature-checklist — your action / ops)
- 🔑 **Refresh expired WhatsApp access token** (Meta System User permanent token) — cards won't deliver until then.
- 🚀 **Redeploy Railway** to pick up the committed checkpointer fix (deployed image was stale).
- 🔒 Rotate all API keys (Groq/Maps appeared in plaintext during dev) before real production.
- 🧹 Remove `GET /discovery/debug/maps-key` (leaks key metadata).
- 🗄️ Move in-memory `_pending_approvals` / discovery `_tasks` dicts → Redis/Postgres before scaling (multi-worker safety).
- 🧾 Register Stripe webhook in Stripe Dashboard; apply pending Alembic migrations on prod DB.

---

## 7. My Suggestions (value-add)
1. **Ship autonomy modes first.** It's the highest-leverage P0 — the HITL plumbing is already everywhere, so
   formalizing Assist/Semi/Full is mostly a gating flag and unlocks the blueprint's headline governance promise.
2. **Surface KPIs by reusing the calibration digest.** You already send WhatsApp summaries from the calibration
   task — point a metrics query at the same send path and you get L13 cheaply.
3. **Defer paid multimodal vision until revenue justifies it.** Text-approximation is "good enough" for now;
   when you do add vision, gate it to leads scoring >8 to honor the blueprint's own 85%-margin unit-economics rule.
4. **Treat the Context Router as the keystone.** It unblocks verticalization (L17), niche onboarding data (L12),
   and the subdomain wedge — three blueprint moats for one piece of infra. The `vertical_tag` plumbing is already there.
5. **Consolidate in-memory state to Redis before any scaling push.** `_pending_approvals` and `_tasks` are the
   two things most likely to bite you under multi-worker load on Railway.
6. **Build the Retention agent next among P1s** — it's the cheapest new agent (the CRM event already exists) and
   directly grows buyer LTV, which is the blueprint's long-tail revenue thesis.

---

## 8. Phase 5+ / Future — Agency Evolution Engine (out of core completion %)

> These are the blueprint's **agency-side / self-evolving** layers (9 & 22). They're real and ambitious but sit
> *beyond* the founder-facing product. Tracked separately so they don't distort the core score.

| Capability (Blueprint) | What it'd take |
|---|---|
| **Adaptive Strategy Engine** (L9) | Background GTM-experiment generator + niche discovery, with a hard execution guardrail and WhatsApp deploy-approval prompt |
| **Retool Admin/Owner Control Desk** (L22) | Separate operational plane for *your* team: global config, model training, multi-tenant health |
| **24/7 Competitive Intelligence Crawler** (L22) | Always-on market/pricing/competitor monitor → strategic digest to owner |
| **Zero-Downtime Hot-Swapping** (L22) | Live model/workflow swap with async state-queue isolation of active pipelines |
| **Self-Optimizing MCP & Schema Adaptation** (L22) | Auto-refactor MCP servers + vector schemas + background data migration on third-party changes |
| **Self-Correcting Sandbox Loops** (L22) | Sandboxed test of new code/workflows, validating 85%+ margin before deploy |
| **Cryptographic Admin Governance Gate** (L22) | Unbypassable signed-approval boundary for any platform-wide code/pricing change (the HMAC governance gate is a *seed* of this) |

---

## 9. Bottom Line

**Core founder-facing product (Layers 1–21): ~70% of the blueprint's intent is built and tested.**

- **Solid / done (✅):** the full intelligence + outreach spine — discovery, 5-dim scoring, the agent swarm,
  human-assisted negotiation, calibration/learning, governance gate, Stripe billing, CRM sync, single-link RAG
  onboarding. The hard "does the AI actually work end-to-end" question is answered **yes** (264 tests, live-verified).
- **Partial (🟡) — the next frontier:** verticalization (Context Router + subdomains + niche onboarding),
  the full "Distribution OS" breadth (inventory, contracts, retention), conversational/no-dashboard ops,
  auto domain provisioning, a metrics surface, and true multimodal vision.
- **Deferred (⏭️):** the agency evolution engine (Layers 9 & 22) — powerful, but a Phase 5+ concern.

**One-sentence summary:** You've built a working brain and voice; what remains is mostly *breadth and packaging*
(verticalization, the full distribution OS, and the headless WhatsApp UX) plus the long-horizon agency
self-evolution layer — and the single highest-leverage next move is to formalize **autonomy modes** and a
**Context Router**, since both ride on infrastructure you already have.
