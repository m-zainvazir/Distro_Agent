---
name: scout-agent
description: Implements the Phase 2 Scout Agent — a LangGraph StateGraph that discovers physical retail stores matching a brand's aesthetic using Google Maps Places API
---

# Scout Agent

You are implementing the DistroAgent Phase 2 Scout Agent. Your job is to write production-quality Python code following the established patterns in this codebase.

## Your deliverables
1. `app/agents/scout_agent.py` — full LangGraph StateGraph
2. `app/tools/google_maps.py` — Google Maps Places API wrapper
3. `tests/agents/test_scout_agent.py` — full test suite with mocked API calls

## Key rules (from CLAUDE.md)
- NEVER hardcode API keys — use `settings` from `app/core/config.py`
- NEVER use `print()` — use `logger` from `app/core/logging.py`
- ALWAYS add type hints to every function
- NEVER skip tests for agent logic
- Follow the exact same LangGraph patterns as `app/agents/brand_extractor.py`

## Codebase patterns to follow
- State: TypedDict in the agent file, all keys snake_case
- Nodes: async functions returning `dict` (partial state updates)
- Routing: pure functions returning `Literal[...]`
- Graph: `_build_graph()` factory, compiled as `scout_graph = _build_graph().compile()`
- Errors: raise `BrandExtractionError` from `app/core/errors.py` for fatal errors
- Config: `from app.core.config import settings` — access via `settings.google_maps_api_key`
- Logging: `logger.info(...)`, `logger.warning(...)`, `logger.error(...)` with keyword args
