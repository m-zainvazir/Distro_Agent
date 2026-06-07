import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.brand_extractor import BrandExtractorState, brand_extractor_graph
from app.core.errors import BrandExtractionError
from app.core.logging import logger
from app.models.brand_profile import BrandProfile
from app.models.campaign import BrandProfileRecord


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
        "canonical_name": "",
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


async def save_brand_profile_record(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_url: str,
    profile: BrandProfile,
) -> BrandProfileRecord:
    record = BrandProfileRecord(
        tenant_id=tenant_id,
        brand_url=brand_url,
        brand_name=profile.brand_name,
        aesthetic_keywords=profile.aesthetic_keywords,
        price_range_min=profile.price_range[0],
        price_range_max=profile.price_range[1],
        embedding_vector=profile.embedding_vector,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("brand_profile_saved", brand_name=profile.brand_name, record_id=str(record.id))
    return record


async def upsert_brand_embedding(
    record_id: uuid.UUID,
    tenant_id: uuid.UUID,
    profile: BrandProfile,
) -> None:
    if not profile.embedding_vector:
        logger.warning("upsert_brand_embedding_skipped", reason="empty vector")
        return

    from app.core.qdrant import get_qdrant_client
    from qdrant_client.models import PointStruct

    client = get_qdrant_client()
    await client.upsert(
        collection_name="brand_embeddings",
        points=[
            PointStruct(
                id=str(record_id),
                vector=profile.embedding_vector,
                payload={
                    "tenant_id": str(tenant_id),
                    "brand_name": profile.brand_name,
                    "aesthetic_keywords": profile.aesthetic_keywords,
                },
            )
        ],
    )
    logger.info("brand_embedding_upserted", record_id=str(record_id))
