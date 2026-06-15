from app.agents.scout_agent import ScoutState, scout_graph
from app.core.logging import logger
from app.models.brand_profile import BrandProfile


async def scout_stores(
    brand_profile: BrandProfile,
    vertical_tag: str,
    target_location: str,
    max_stores: int = 5,
) -> tuple[list[dict], list[str]]:
    """Run the scout agent and return (store dicts, errors).

    Each store dict has keys: name, address, google_place_id, instagram_handle,
    vibe_score, lead_score, status.
    """
    initial_state: ScoutState = {
        "brand_profile": brand_profile,
        "vertical_tag": vertical_tag,
        "target_location": target_location,
        "max_stores": max_stores,
        "search_queries": [],
        "raw_places": [],
        "enriched_stores": [],
        "discovered_stores": [],
        "errors": [],
    }

    result = await scout_graph.ainvoke(initial_state)

    scout_errors: list[str] = result.get("errors", [])
    discovered_stores: list[dict] = result.get("discovered_stores", [])

    if scout_errors:
        logger.warning(
            "scout_completed_with_errors",
            location=target_location,
            brand=brand_profile.brand_name,
            errors=scout_errors,
            store_count=len(discovered_stores),
        )
    else:
        logger.info(
            "scout_complete",
            location=target_location,
            brand=brand_profile.brand_name,
            store_count=len(discovered_stores),
        )

    return discovered_stores, scout_errors
