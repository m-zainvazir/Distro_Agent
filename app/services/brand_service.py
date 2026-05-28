from app.agents.brand_extractor import BrandExtractorState, brand_extractor_graph
from app.core.errors import BrandExtractionError
from app.core.logging import logger
from app.models.brand_profile import BrandProfile


async def extract_brand(
    brand_url: str,
    vertical_tag: str,
    brand_name: str = "",
) -> BrandProfile:
    initial_state: BrandExtractorState = {
        "brand_url": brand_url,
        "brand_name": brand_name,
        "vertical_tag": vertical_tag,
        "platform": "",
        "raw_catalog": [],
        "about_text": "",
        "image_urls": [],
        "downloaded_images": [],
        "analysis": {},
        "embedding": [],
        "primary_colors": [],
        "brand_profile": None,
        "token_usage": {},
        "error": None,
    }

    result = await brand_extractor_graph.ainvoke(initial_state)

    token_usage = result.get("token_usage", {})
    logger.info(
        "brand_extraction_complete",
        url=brand_url or brand_name,
        input_tokens=token_usage.get("input_tokens"),
        output_tokens=token_usage.get("output_tokens"),
    )

    if result.get("error") and result.get("brand_profile") is None:
        raise BrandExtractionError(
            message=result["error"],
            retry_suggestion="Check the URL or brand name and try again.",
        )

    profile: BrandProfile = result["brand_profile"]
    return profile
