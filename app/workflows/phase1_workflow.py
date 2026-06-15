"""
Phase 1 orchestration workflow.

Chains brand extraction → store scouting → lead scoring → report generation
into a single LangGraph StateGraph. LangSmith tracing is enabled automatically
when LANGSMITH_API_KEY and LANGCHAIN_TRACING_V2=true are set in the environment.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.core.errors import BrandExtractionError
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import ScoredStore, StoreCandidate
from app.services.analyst_service import score_stores
from app.services.brand_service import extract_brand
from app.services.scout_service import scout_stores

# Enable LangSmith tracing via environment variables that LangGraph reads
if settings.langsmith_api_key:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)

_ERROR_THRESHOLD = 3   # errors > this → route to error_handler


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Phase1State(TypedDict):
    brand_url: str
    vertical_tag: str
    target_location: str        # added: scout requires a location to search
    tenant_id: str
    brand_profile: BrandProfile | None
    store_candidates: list[StoreCandidate]
    scored_stores: list[ScoredStore]
    report_url: str
    errors: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scout_dict_to_candidate(d: dict) -> StoreCandidate:
    """Convert a scout agent result dict to a StoreCandidate Pydantic model.

    The scout enriches each store with Google categories, website, price tier,
    and review snippets — carry those through so the analyst's category, price,
    and wholesale scorers have real data to work with. Instagram metrics aren't
    available from Google, so those remain None (engagement scorer handles it).
    """
    address = d.get("address", "")
    parts = [p.strip() for p in address.split(",")]
    # "123 Main St, Brooklyn, NY 11201" → city=parts[-2], state=parts[-1] first word
    city = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")
    state_str = parts[-1].split()[0] if parts and parts[-1] else ""

    return StoreCandidate(
        place_id=d.get("google_place_id", ""),
        name=d.get("name", ""),
        address=address,
        city=city,
        state=state_str,
        google_categories=d.get("google_categories", []),
        website_url=d.get("website_url") or None,
        instagram_handle=d.get("instagram_handle") or None,
        instagram_followers=None,
        instagram_posts_last_30_days=None,
        storefront_image_urls=[],
        price_tier=d.get("price_tier"),
        review_snippets=d.get("review_snippets", []),
        is_chain=False,
    )


def _has_too_many_errors(state: Phase1State) -> bool:
    return len(state.get("errors", [])) > _ERROR_THRESHOLD


def _generate_report_markdown(state: Phase1State) -> str:
    profile = state["brand_profile"]
    scored = state["scored_stores"]
    high = [s for s in scored if s.outreach_priority == "HIGH"]
    medium = [s for s in scored if s.outreach_priority == "MEDIUM"]

    lines = [
        f"# Phase 1 Report — {profile.brand_name if profile else 'Unknown Brand'}",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Tenant:** {state['tenant_id']}",
        f"**Location:** {state.get('target_location', 'N/A')}",
        f"**Vertical:** {state['vertical_tag']}",
        "",
        "---",
        "",
        "## Brand Profile",
    ]

    if profile:
        lines += [
            f"- **Name:** {profile.brand_name}",
            f"- **Tagline:** {profile.tagline}",
            f"- **Categories:** {', '.join(profile.product_categories)}",
            f"- **Price range:** ${profile.price_range[0]}–${profile.price_range[1]}",
            f"- **Wholesale readiness:** {profile.wholesale_readiness_score}/10",
            "",
        ]

    lines += [
        "---",
        "",
        f"## Store Results — {len(scored)} stores scored",
        f"- HIGH priority: {len(high)}",
        f"- MEDIUM priority: {len(medium)}",
        f"- LOW priority: {len(scored) - len(high) - len(medium)}",
        "",
        "### Top Stores",
        "",
    ]

    for i, s in enumerate(scored[:10], 1):
        lines += [
            f"**{i}. {s.store.name}** — {s.store.city}, {s.store.state}",
            f"   Score: {s.final_score:.1f}/10 | Priority: {s.outreach_priority}",
            f"   {s.match_summary}",
            "",
        ]

    if state.get("errors"):
        lines += ["---", "", "## Errors", ""]
        for err in state["errors"]:
            lines.append(f"- {err}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def brand_extractor_node(state: Phase1State) -> dict:
    errors = list(state.get("errors", []))
    try:
        profile = await extract_brand(
            brand_url=state["brand_url"],
            vertical_tag=state["vertical_tag"],
        )
        logger.info("phase1_brand_extracted", brand=profile.brand_name)
        return {"brand_profile": profile, "errors": errors}
    except BrandExtractionError as exc:
        errors.append(f"brand_extractor: {exc}")
        logger.error("phase1_brand_extraction_failed", error=str(exc))
        return {"brand_profile": None, "errors": errors}
    except Exception as exc:
        errors.append(f"brand_extractor: unexpected error — {exc}")
        logger.error("phase1_brand_extraction_unexpected", error=str(exc))
        return {"brand_profile": None, "errors": errors}


async def scout_node(state: Phase1State) -> dict:
    errors = list(state.get("errors", []))
    profile = state.get("brand_profile")

    if profile is None:
        errors.append("scout: skipped — no brand profile available")
        return {"store_candidates": [], "errors": errors}

    try:
        raw_stores, scout_errors = await scout_stores(
            brand_profile=profile,
            vertical_tag=state["vertical_tag"],
            target_location=state.get("target_location", "New York, NY"),
        )
        errors.extend(scout_errors)
        candidates = [_scout_dict_to_candidate(d) for d in raw_stores]
        logger.info("phase1_scout_complete", count=len(candidates))
        return {"store_candidates": candidates, "errors": errors}
    except Exception as exc:
        errors.append(f"scout: {exc}")
        logger.error("phase1_scout_failed", error=str(exc))
        return {"store_candidates": [], "errors": errors}


async def analyst_node(state: Phase1State) -> dict:
    errors = list(state.get("errors", []))
    candidates = state.get("store_candidates", [])
    profile = state.get("brand_profile")

    if not candidates or profile is None:
        errors.append("analyst: skipped — no candidates or brand profile")
        return {"scored_stores": [], "errors": errors}

    try:
        scored = await score_stores(
            brand_profile=profile,
            store_candidates=candidates,
        )
        logger.info("phase1_analyst_complete", scored=len(scored))
        return {"scored_stores": scored, "errors": errors}
    except Exception as exc:
        errors.append(f"analyst: {exc}")
        logger.error("phase1_analyst_failed", error=str(exc))
        return {"scored_stores": [], "errors": errors}


async def report_generator_node(state: Phase1State) -> dict:
    errors = list(state.get("errors", []))
    try:
        Path("reports").mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"reports/phase1_{state['tenant_id']}_{timestamp}.md"

        report_md = _generate_report_markdown(state)
        Path(filename).write_text(report_md, encoding="utf-8")

        logger.info("phase1_report_generated", path=filename)
        return {"report_url": filename, "errors": errors}
    except Exception as exc:
        errors.append(f"report_generator: {exc}")
        logger.error("phase1_report_failed", error=str(exc))
        return {"report_url": "", "errors": errors}


async def error_handler_node(state: Phase1State) -> dict:
    errors = state.get("errors", [])
    logger.error(
        "phase1_error_threshold_exceeded",
        error_count=len(errors),
        errors=errors,
        brand_url=state.get("brand_url"),
        tenant_id=state.get("tenant_id"),
    )
    # Return whatever partial results exist — never crash
    return {
        "report_url": "",
        "scored_stores": state.get("scored_stores", []),
        "store_candidates": state.get("store_candidates", []),
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_after_brand_extractor(state: Phase1State) -> str:
    return "error_handler" if _has_too_many_errors(state) else "scout"


def route_after_scout(state: Phase1State) -> str:
    return "error_handler" if _has_too_many_errors(state) else "analyst"


def route_after_analyst(state: Phase1State) -> str:
    return "error_handler" if _has_too_many_errors(state) else "report_generator"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    graph = StateGraph(Phase1State)

    graph.add_node("brand_extractor", brand_extractor_node)
    graph.add_node("scout", scout_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("error_handler", error_handler_node)

    graph.set_entry_point("brand_extractor")

    graph.add_conditional_edges("brand_extractor", route_after_brand_extractor)
    graph.add_conditional_edges("scout", route_after_scout)
    graph.add_conditional_edges("analyst", route_after_analyst)
    graph.add_edge("report_generator", END)
    graph.add_edge("error_handler", END)

    return graph


phase1_graph = _build_graph().compile()
