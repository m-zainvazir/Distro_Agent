# DistroAgent — Phase 1 Status & Potential Problems

## What it is
Multi-tenant B2B distribution SaaS. Input a brand URL + vertical + city → it extracts a brand profile, scouts indie retail stores via Google Maps, scores them for fit, and produces a ranked report.

## Architecture
3 LangGraph `StateGraph` agents (Brand Extractor → Scout → Analyst) chained by `phase1_workflow.py` + a report generator, fronted by FastAPI with Celery/Redis async jobs and a Next.js UI. Postgres + Qdrant for persistence.

## Status — Phase 1 functionally complete & verified
- 127 tests passing, ruff + mypy clean, Docker infra 9/9 acceptance criteria
- Verified end-to-end against Allbirds, Kylie Cosmetics, Golde

## The two known problems from real-world testing that matter most going into Phase 2

1. **Brand mis-naming** — extractor picks the first product line (Allbirds→"Trino") or hallucinates ("Whimsy Wellness Co."). Needs catalog sampling + name constraint.

2. **🔴 The big one — full-pipeline scoring is broken.** Every store scores an identical ~4.1/10 LOW. Root cause is the scout→analyst handoff: `scout_agent.py::build_candidates_node` doesn't return `google_categories`/`review_snippets`, and `phase1_workflow.py::_scout_dict_to_candidate` hardcodes them to empty. So category/wholesale/engagement scorers run on blank data. The analyst works fine in isolation (unit tests + `/scoring/score-batch` prove it) — it's purely a data-passing gap.

## Other open gaps
- `/discovery` path doesn't persist to DB/Qdrant
- vision is text-approximated (free-tier)
- API keys need rotation before deploy
- frontend placeholders (Calendly, vercel.json)
