from typing import Literal
from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from app.core.errors import BrandExtractionError
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.tools.brand_discoverer import discover_brand_url
from app.tools.catalog_fetcher import fetch_etsy_catalog, fetch_shopify_catalog, scrape_with_playwright
from app.tools.color_extractor import extract_colors_from_images
from app.tools.embedding_generator import generate_brand_embedding
from app.tools.image_downloader import download_images
from app.tools.platform_detector import detect_platform
from app.tools.vision_analyzer import analyze_brand_aesthetics


class BrandExtractorState(TypedDict):
    brand_url: str
    brand_name: str
    vertical_tag: str
    platform: str
    raw_catalog: list[dict]
    about_text: str
    canonical_name: str   # authoritative store name from platform metadata
    image_urls: list[str]
    downloaded_images: list[str]
    primary_colors: list[str]
    analysis: dict
    embedding: list[float]
    brand_profile: BrandProfile | None
    token_usage: dict[str, int]
    error: str | None


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _sample_products(products: list[dict], count: int = 8) -> list[dict]:
    """Return up to count products sampled evenly across the full catalog."""
    if len(products) <= count:
        return products
    step = max(1, len(products) // count)
    return products[::step][:count]


async def discover_url_node(state: BrandExtractorState) -> dict:
    try:
        url = await discover_brand_url(state["brand_name"], state["vertical_tag"])
        return {"brand_url": url, "error": None}
    except BrandExtractionError as exc:
        return {"brand_url": "", "error": str(exc)}


async def detect_platform_node(state: BrandExtractorState) -> dict:
    try:
        platform = await detect_platform(state["brand_url"])
        return {"platform": platform, "error": None}
    except Exception as exc:
        return {"platform": "generic", "error": f"Platform detection failed: {exc}"}


async def fetch_catalog_node(state: BrandExtractorState) -> dict:
    try:
        if state["platform"] == "shopify":
            products, about_text, canonical_name = await fetch_shopify_catalog(state["brand_url"])
        elif state["platform"] == "etsy":
            products, about_text, canonical_name = await fetch_etsy_catalog(state["brand_url"])
        else:
            products, about_text, canonical_name = await scrape_with_playwright(state["brand_url"])

        sampled = _sample_products(products, count=8)
        image_urls: list[str] = []
        for p in sampled:
            if "images" in p:
                for img in p["images"]:
                    src = img.get("src", "")
                    if src:
                        image_urls.append(src)
            elif p.get("image"):
                image_urls.append(str(p["image"]))

        return {
            "raw_catalog": products,
            "about_text": about_text,
            "canonical_name": canonical_name,
            "image_urls": image_urls[:10],
            "error": None,
        }
    except Exception as exc:
        return {
            "raw_catalog": [],
            "about_text": "",
            "canonical_name": "",
            "image_urls": [],
            "error": str(exc),
        }


async def download_images_node(state: BrandExtractorState) -> dict:
    try:
        downloaded = await download_images(state["image_urls"], max_images=5)
        colors = extract_colors_from_images(downloaded)
        return {"downloaded_images": downloaded, "primary_colors": colors}
    except Exception as exc:
        logger.warning("download_images_failed", error=str(exc))
        return {"downloaded_images": [], "primary_colors": []}


async def analyze_aesthetics_node(state: BrandExtractorState) -> dict:
    try:
        analysis, token_usage = await analyze_brand_aesthetics(
            about_text=state["about_text"],
            products=_sample_products(state["raw_catalog"], count=8),
            vertical_tag=state["vertical_tag"],
            canonical_name=state.get("canonical_name", ""),
        )
        logger.info(
            "groq_token_usage",
            node="analyze_aesthetics",
            input_tokens=token_usage.get("input_tokens", 0),
            output_tokens=token_usage.get("output_tokens", 0),
        )
        return {"analysis": analysis, "token_usage": token_usage}
    except Exception as exc:
        logger.error("aesthetics_analysis_failed", error=str(exc))
        return {"analysis": {}, "token_usage": {}, "error": str(exc)}


async def generate_embedding_node(state: BrandExtractorState) -> dict:
    analysis = state.get("analysis", {})
    profile_text = (
        f"{analysis.get('brand_name', '')} {analysis.get('tagline', '')} "
        f"{' '.join(analysis.get('aesthetic_keywords', []))} "
        f"{analysis.get('brand_voice_description', '')}"
    )
    try:
        embedding = await generate_brand_embedding(profile_text)
        return {"embedding": embedding}
    except Exception as exc:
        logger.error("embedding_generation_failed", error=str(exc))
        return {"embedding": []}


async def build_profile_node(state: BrandExtractorState) -> dict:
    analysis = state.get("analysis", {})
    embedding = state.get("embedding", [])
    raw_images = state["image_urls"][:5]

    try:
        # canonical_name from platform metadata overrides whatever the LLM inferred
        brand_name = state.get("canonical_name") or analysis.get("brand_name", "")
        profile = BrandProfile(
            brand_name=brand_name,
            tagline=analysis.get("tagline", ""),
            primary_colors=state.get("primary_colors", []),
            aesthetic_keywords=analysis.get("aesthetic_keywords", []),
            product_categories=analysis.get("product_categories", []),
            price_range=(
                _safe_float(analysis.get("price_range_min", 0.0)),
                _safe_float(analysis.get("price_range_max", 0.0)),
            ),
            brand_voice_description=analysis.get("brand_voice_description", ""),
            wholesale_readiness_score=_safe_float(analysis.get("wholesale_readiness_score", 0.0)),
            raw_product_images=raw_images,
            embedding_vector=embedding,
        )
        return {"brand_profile": profile}
    except Exception as exc:
        logger.error("build_profile_failed", error=str(exc))
        return {"brand_profile": None, "error": str(exc)}


async def build_partial_profile_node(state: BrandExtractorState) -> dict:
    profile = BrandProfile(
        brand_name="",
        tagline="",
        primary_colors=[],
        aesthetic_keywords=[],
        product_categories=[],
        price_range=(0.0, 0.0),
        brand_voice_description="",
        wholesale_readiness_score=0.0,
        raw_product_images=[],
        embedding_vector=[],
    )
    logger.warning("no_products_found_partial_profile", url=state["brand_url"])
    return {"brand_profile": profile}


async def error_node(state: BrandExtractorState) -> dict:
    logger.error("brand_extraction_error", error=state.get("error"), url=state["brand_url"])
    return {"brand_profile": None}


def route_entry(state: BrandExtractorState) -> Literal["discover_url", "detect_platform"]:
    if state.get("brand_url"):
        return "detect_platform"
    return "discover_url"


def route_after_discover(state: BrandExtractorState) -> Literal["detect_platform", "error"]:
    if state.get("error"):
        return "error"
    return "detect_platform"


def route_after_catalog(
    state: BrandExtractorState,
) -> Literal["download_images", "build_partial_profile", "error"]:
    if state.get("error"):
        return "error"
    if not state.get("raw_catalog"):
        return "build_partial_profile"
    return "download_images"


def route_after_aesthetics(
    state: BrandExtractorState,
) -> Literal["generate_embedding", "error"]:
    if state.get("error"):
        return "error"
    return "generate_embedding"


def _build_graph() -> StateGraph:
    graph = StateGraph(BrandExtractorState)

    graph.add_node("discover_url", discover_url_node)
    graph.add_node("detect_platform", detect_platform_node)
    graph.add_node("fetch_catalog", fetch_catalog_node)
    graph.add_node("download_images", download_images_node)
    graph.add_node("analyze_aesthetics", analyze_aesthetics_node)
    graph.add_node("generate_embedding", generate_embedding_node)
    graph.add_node("build_profile", build_profile_node)
    graph.add_node("build_partial_profile", build_partial_profile_node)
    graph.add_node("error", error_node)

    graph.set_conditional_entry_point(route_entry)
    graph.add_conditional_edges("discover_url", route_after_discover)
    graph.add_edge("detect_platform", "fetch_catalog")
    graph.add_conditional_edges("fetch_catalog", route_after_catalog)
    graph.add_edge("download_images", "analyze_aesthetics")
    graph.add_conditional_edges("analyze_aesthetics", route_after_aesthetics)
    graph.add_edge("generate_embedding", "build_profile")
    graph.add_edge("build_profile", END)
    graph.add_edge("build_partial_profile", END)
    graph.add_edge("error", END)

    return graph


brand_extractor_graph = _build_graph().compile()
