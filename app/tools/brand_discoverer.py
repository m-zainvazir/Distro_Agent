import asyncio

from duckduckgo_search import DDGS

from app.core.errors import BrandExtractionError
from app.core.logging import logger


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def discover_brand_url(brand_name: str, vertical_tag: str) -> str:
    """Use DuckDuckGo to find a brand's store URL from its name."""
    queries = [
        f'site:myshopify.com "{brand_name}"',
        f'site:etsy.com/shop "{brand_name}"',
        f'"{brand_name}" {vertical_tag} official store',
    ]

    for query in queries:
        try:
            results = await asyncio.to_thread(_ddg_search, query, 5)
            for r in results:
                url = r.get("href", "")
                if url and brand_name.lower().replace(" ", "") in url.lower().replace("-", "").replace("_", ""):
                    logger.info("brand_url_discovered", brand_name=brand_name, url=url, query=query)
                    return url
            # Accept first result from site-specific queries even without name match
            if results and ("myshopify.com" in query or "etsy.com" in query):
                url = results[0].get("href", "")
                if url:
                    logger.info("brand_url_discovered_fallback", brand_name=brand_name, url=url)
                    return url
        except Exception as exc:
            logger.warning("ddg_search_failed", query=query, error=str(exc))

    raise BrandExtractionError(
        message=f"Could not find a store URL for brand '{brand_name}'",
        retry_suggestion="Try providing the brand_url directly instead of brand_name.",
    )
