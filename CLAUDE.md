# CLAUDE.md — DistroAgent Project Constitution

## Project Overview
DistroAgent is a multi-tenant, multi-agent B2B distribution SaaS. Stack: Python 3.11 · LangGraph · FastAPI · PostgreSQL · Qdrant · Redis

## Critical Rules (ALWAYS FOLLOW)
- NEVER hardcode API keys — use environment variables from .env
- NEVER skip writing tests for agent logic
- ALWAYS add type hints to every Python function
- ALWAYS run `make lint` before declaring any task done
- ALWAYS check existing patterns before creating new files
- NEVER use print() — use the logger from app/core/logging.py

## Project Structure
distroagent/
├── app/
│ ├── agents/ # LangGraph agents (one file per agent)
│ ├── api/ # FastAPI routers
│ ├── core/ # Config, logging, database setup
│ ├── models/ # SQLAlchemy models
│ ├── services/ # Business logic services
│ ├── tools/ # LangGraph tool functions
│ └── workflows/ # LangGraph StateGraph definitions
├── tests/ # Mirror of app/ structure
├── .claude/ # Claude Code config
│ ├── commands/ # Custom slash commands
│ └── agents/ # Subagent definitions
├── specs/ # Feature specifications (READ FIRST)
├── Makefile # All runnable commands
└── CLAUDE.md # This file


## Common Commands
- `make dev`         → Start development server
- `make test`        → Run all tests
- `make lint`        → Ruff + MyPy check
- `make db-migrate`  → Apply database migrations
- `make agent-test`  → Test agent workflows

## Agent Architecture (CRITICAL)
We use LangGraph StateGraph. EVERY agent must:
1. Define its State TypedDict in its own file
2. Have a corresponding test in tests/agents/
3. Be registered in app/workflows/registry.py
4. Have a spec in specs/ before being built

## Database Rules
- Use Alembic for ALL migrations — never edit tables manually
- Multi-tenant: every query MUST filter by tenant_id
- Use async SQLAlchemy sessions

## API Rules
- All endpoints under /api/v1/
- Use Pydantic v2 for request/response models
- Return structured errors with error codes