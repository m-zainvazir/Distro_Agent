# DistroAgent — Phase 1 Complete

> Status as of 2026-06-03. Phase 1 (brand discovery → store scouting → lead scoring → report) is
> functionally complete and verified end-to-end against real brands.

---

## 1. What DistroAgent Is

DistroAgent is a **multi-tenant B2B distribution SaaS**. The problem it solves: a consumer brand
(skincare, footwear, home goods, etc.) wants to get its products onto the shelves of independent
retail stores, but finding the *right* stores — ones whose aesthetic, price point, and customer base
actually fit the brand — is slow manual work.

Given just a **brand URL and a target city**, DistroAgent automatically:
1. Extracts a structured profile of the brand (aesthetic, products, pricing, voice).
2. Discovers real indie retail stores in that city via Google Maps.
3. Scores and ranks each store on how well it fits the brand.
4. Produces a report with outreach priorities and a written rationale for each match.

---

## 2. The Product in One Flow

```
INPUT:  brand_url (or brand_name) + vertical_tag + target_location
          │
          ▼
  ┌───────────────┐   ┌───────────┐   ┌──────────────┐   ┌──────────────────┐
  │ Brand          │→ │ Scout      │→ │ Analyst       │→ │ Report           │
  │ Extractor      │   │ (Maps)    │   │ (5-dim score) │   │ Generator        │
  └───────────────┘   └───────────┘   └──────────────┘   └──────────────────┘
          │                                                        │
          ▼                                                        ▼
OUTPUT: ranked ScoredStore list (HIGH/MEDIUM/LOW priority + match summary)
        + markdown report in reports/
```

---

## 3. Architecture

**Stack:** Python 3.11 · LangGraph · FastAPI · PostgreSQL · Qdrant · Redis · Celery · Next.js 16

**Three LangGraph agents**, each a self-contained `StateGraph`:

| Agent | File | Node chain |
|---|---|---|
| Brand Extractor | `app/agents/brand_extractor.py` | discover_url → detect_platform → fetch_catalog → download_images → analyze_aesthetics → generate_embedding → build_profile |
| Scout | `app/agents/scout_agent.py` | validate_inputs → generate_queries → search_maps → enrich_stores → filter_stores → build_candidates |
| Analyst | `app/agents/analyst_agent.py` | validate_inputs → score_text_dimensions → score_vision → compute_final_scores → sort_and_package |

**Orchestration:** `app/workflows/phase1_workflow.py` chains all three plus a report generator into one
`phase1_graph`. It tolerates up to 3 errors before routing to an error handler — it never crashes,
always returns partial results.

**Services layer** (`app/services/`) wraps each agent for the API/workflow:
`extract_brand()`, `scout_stores()`, `score_stores()`.

---

## 4. Feature List

- **Brand extraction, 3 strategies:** Shopify `/products.json` API · Etsy Open API v3 · Playwright
  headless-browser scrape for any generic site (bypasses bot detection).
- **URL discovery from a name:** DuckDuckGo search finds a brand's store URL when only the name is given.
- **Color extraction:** dominant hex palette from product images (ColorThief).
- **Free local embeddings:** `sentence-transformers BAAI/bge-small-en-v1.5`, 384-dim, no API cost.
- **Store scouting:** Google Places API (New) text search + details, with chain-store filtering
  (Sephora, Target, etc.) and rate-limit retry.
- **5-dimension lead scoring:** category, price, engagement, wholesale signals (text, 65%) + visual
  vibe (35%), with a $0.50 vision budget cap.
- **LLM match summaries:** each store gets a 2-sentence "why it matches" written by Groq.
- **Async jobs:** Celery + Redis run the full pipeline in the background with progress polling.
- **HTML report:** markdown report rendered to HTML for the frontend.
- **Dev tooling:** auto-lint hook (ruff + mypy on every edit), Docker Compose infra, Alembic migrations.

---

## 5. API Surface

Base prefix `/api/v1`. Health at `/health`.

| Endpoint | Method | Purpose | Persists to DB? |
|---|---|---|---|
| `/brands/extract` | POST | Extract one brand profile | **Yes** — Postgres + Qdrant (needs real `tenant_id` UUID) |
| `/scoring/score-batch` | POST | Score a supplied list of stores against a brand | No |
| `/discovery/start` | POST | Kick off the **full** pipeline as a Celery job | No (writes markdown report only) |
| `/discovery/{task_id}/status` | GET | Poll progress (0–100) | — |
| `/discovery/{task_id}/report` | GET | Fetch final stores + HTML report | — |

**Important nuance:** `/brands/extract` is the only path that writes to Postgres/Qdrant and therefore
requires a real tenant row (foreign-key enforced). The `/discovery` pipeline currently produces a
report but does **not** persist results — closing that gap is a Phase 2 item.

---

## 6. Data Model

**PostgreSQL** (`app/models/campaign.py`), all tenant-scoped via `TenantMixin`:

```
tenants
 ├── brand_profiles      (brand_url, brand_name, aesthetic_keywords, price_range, embedding_vector)
 ├── store_candidates    (name, address, google_place_id, instagram_handle, vibe_score, lead_score, status)
 └── outreach_campaigns  (status)
       └── outreach_emails (subject, body, sent_at, reply_received, outcome)   ← built, not yet used
```

**Qdrant:** collection `brand_embeddings`, 384-dim, cosine distance. Embeddings are written on
`/brands/extract` but not yet queried (Phase 2: similarity search).

---

## 7. How to Run It

Three ways, from simplest to most complete:

### A. Direct script (no DB, no Celery, no frontend) — best for a quick real test
Only needs `GROQ_API_KEY` + `GOOGLE_MAPS_API_KEY` in `.env` + internet.
```powershell
.venv\Scripts\python -m scripts.run_phase1_test "https://www.allbirds.com" "footwear" "Los Angeles, CA"
```
Prints the brand profile + ranked stores and writes a report to `reports/`.

### B. API + Celery (the real async path)
```powershell
docker compose up -d                                              # Postgres + Qdrant
# (Redis already running on :6379)
.venv\Scripts\python -m celery -A app.celery_app worker --pool=solo --loglevel=info   # terminal 1
.venv\Scripts\uvicorn app.main:app --reload --port 8000                                # terminal 2
# then:
curl -X POST http://localhost:8000/api/v1/discovery/start -H "Content-Type: application/json" `
  -d '{"brand_url":"https://www.allbirds.com","vertical_tag":"footwear","location":"Los Angeles, CA"}'
# poll /api/v1/discovery/{task_id}/status, then GET /report
```

### C. Full stack + frontend UI
Do (B), then:
```powershell
cd frontend; npm install; npm run dev      # http://localhost:3000
```
Fill the form in the browser; results render live.

**Prerequisites recap:** Python venv with deps installed; Docker Desktop (for B/C); Node 20+ (for C);
`playwright install chromium` only if scraping non-Shopify/Etsy "generic" sites.

> **⚠️ Editing `.env` requires a restart.** Settings load once at process startup
> (`app/core/config.py`: `settings = Settings()`), so the running uvicorn and Celery worker keep using
> the values they loaded. After changing `.env` (e.g. a key), `Ctrl+C` and restart **both** the API and
> the Celery worker for the change to take effect.

---

## 8. What's Done & Verified

- ✅ All three agents implemented, registered, and unit-tested.
- ✅ Phase 1 orchestration workflow + Celery task.
- ✅ FastAPI backend (all endpoints) + Next.js frontend.
- ✅ Docker infra (Postgres + Qdrant) — **9/9 acceptance criteria pass**, data persists across restarts,
  tenant isolation enforced by FK.
- ✅ Alembic migrations create all 5 tables.
- ✅ **127 tests passing**, `ruff` clean, `mypy` clean (51 source files).
- ✅ **Verified end-to-end against a real brand** (see §10).

Phase 1 checklist: 15/20 → now ~18/20 with Docker + end-to-end done. Remaining ☐ are CI/`make`
(Windows has no `make`) and hooks polish.

---

## 9. Known Gaps / Loose Ends

1. **Exposed API keys** — the Groq and Google Maps keys appeared in plaintext during development. They
   are safely gitignored in `.env`, but **rotate them before any deployment**.
2. **Discovery path doesn't persist** — `/discovery/start` generates a report but writes nothing to
   Postgres/Qdrant. Wiring persistence + auth is the first Phase 2 task.
3. **Vision is text-approximated** — "visual vibe" is Groq analyzing store text signals, not real image
   analysis (free-tier deviation from the original Claude-vision spec).
4. **Extraction quality depends on catalog order** — for large catalogs, `/products.json` may lead with
   accessories, skewing the detected brand name/price (see §10). A Phase 2 refinement.
5. **Placeholders** — `frontend/.env.local` Calendly URL and `vercel.json` API URL are still stubs.

---

## 10. Real-World Test Results (2026-06-03)

Ran the direct script against three real brands. The pipeline completed every time (~26–38s,
~$0.001 Groq), found real, relevant stores, and wrote reports — but the runs exposed **two distinct
problems**, the second of which is significant.

| Brand | Extracted as | Stores found (all real & relevant) | All scored |
|---|---|---|---|
| Allbirds | "Trino" ❌ | Shoe Lounge LA, DripLA, Shiekh… | 3.2/10 LOW |
| Kylie Cosmetics | "Kylie Cosmetics" ✅ | **Glossier NYC, Bluemercury** + 3 studios | 4.1/10 LOW |
| Golde | "Whimsy Wellness Co." ❌ | Best Wellness Boutique, Herbal by Nature… | 4.1/10 LOW |

**Problem 1 — brand extraction mis-names some brands.** Allbirds → "Trino" (its sock line, listed
first in `/products.json`); Golde → "Whimsy Wellness Co." (an outright hallucination). Only Kylie
extracted correctly. Fix: sample products across the catalog and constrain the LLM to the actual
store name rather than inventing one.

**Problem 2 (the important one) — full-pipeline scoring is effectively non-functional.** Every store,
across every brand, scored an *identical* 4.1/10 (or 3.2) LOW — including Glossier and Bluemercury for
a cosmetics brand, which are ideal matches. Identical scores for completely different stores is the
tell. **Root cause (confirmed in code):** the scout→analyst handoff drops the data the analyst scores
on. `scout_agent.py::build_candidates_node` returns only name/address/place_id/instagram_handle/
vibe_score (no `google_categories`, no `review_snippets`), and `phase1_workflow.py::_scout_dict_to_candidate`
hardcodes `google_categories=[]`, `review_snippets=[]`, `price_tier=None`. So the category, wholesale,
and engagement scorers all run against blank data → constant low scores.

**Takeaway:** orchestration, Maps discovery, reporting, and the analyst *in isolation* all work (the
analyst's unit tests pass with fully-populated `StoreCandidate`s, and `/scoring/score-batch` scores
rich input correctly). The full **discovery** workflow, however, currently produces meaningless rankings
because the scout doesn't carry store categories/reviews/price through to the analyst. This should be
fixed before Phase 2 — see §11.


