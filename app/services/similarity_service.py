"""Qdrant cosine-similarity search + per-tenant store deduplication.

Privacy rules (CRITICAL)
------------------------
- find_similar_brands returns ANONYMIZED aggregates only.
- SimilarBrand intentionally omits: brand_name, tenant_id, store_list,
  contact info, email, phone.  Fields that could identify a competitor
  are stripped at this layer before the response is assembled.
- dedup_stores filters by tenant_id — one tenant never sees another's data.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.core.qdrant import get_qdrant_client
from app.models.store_candidate import StoreCandidate

_QDRANT_COLLECTION = "brand_embeddings"


# ---------------------------------------------------------------------------
# Response model — deliberately minimal to enforce privacy
# ---------------------------------------------------------------------------


class SimilarBrand(BaseModel):
    """Anonymized aggregate — NO identifying fields by design.

    Omitted intentionally: brand_name, tenant_id, store_list, contact,
    email, phone, address, brand_url.
    """

    similarity_score: float
    shared_aesthetic_keywords: list[str]
    price_range: tuple[float, float]
    shared_product_categories: list[str]


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------


async def find_similar_brands(
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    k: int = 5,
) -> list[SimilarBrand]:
    """Return the top-k most similar brands by cosine similarity.

    Excludes the requesting brand itself.  Results are anonymized — only
    aggregated overlaps and similarity scores are returned.

    Args:
        tenant_id: The requesting tenant (used to fetch the query embedding).
        brand_id:  The brand to search from.
        k:         Number of similar brands to return.

    Returns:
        List of :class:`SimilarBrand` with no PII.
    """
    from app.models.campaign import BrandProfileRecord

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BrandProfileRecord).where(
                BrandProfileRecord.id == brand_id,
                BrandProfileRecord.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()

    if record is None or not record.embedding_vector:
        logger.warning("similarity_brand_not_found", brand_id=str(brand_id))
        return []


    client = get_qdrant_client()
    try:
        response = await client.query_points(
            collection_name=_QDRANT_COLLECTION,
            query=list(record.embedding_vector),
            limit=k + 1,  # +1 to account for self being in the index
            with_payload=True,
        )
        hits = response.points
    except Exception as exc:
        logger.error("qdrant_search_failed", error=str(exc))
        return []

    own_keywords: set[str] = set(record.aesthetic_keywords or [])
    results: list[SimilarBrand] = []

    for hit in hits:
        payload = hit.payload or {}

        # Exclude self — compare brand_id stored in payload
        if str(payload.get("brand_id", "")) == str(brand_id):
            continue

        other_keywords: list[str] = payload.get("aesthetic_keywords", [])
        shared_keywords = sorted(own_keywords & set(other_keywords))

        other_categories: list[str] = payload.get("product_categories", [])
        own_categories: set[str] = set(payload.get("own_product_categories", []))
        shared_categories = sorted(own_categories & set(other_categories)) if own_categories else other_categories[:3]

        price_min = float(payload.get("price_range_min", 0.0))
        price_max = float(payload.get("price_range_max", 0.0))

        # Strip all identifying fields — return only anonymized aggregate
        results.append(
            SimilarBrand(
                similarity_score=round(float(hit.score), 4),
                shared_aesthetic_keywords=shared_keywords,
                price_range=(price_min, price_max),
                shared_product_categories=shared_categories,
            )
        )

        if len(results) >= k:
            break

    logger.info("similarity_search_complete", found=len(results))
    return results


# ---------------------------------------------------------------------------
# Store deduplication
# ---------------------------------------------------------------------------


async def dedup_stores(
    tenant_id: uuid.UUID,
    candidates: list[StoreCandidate],
    db: AsyncSession,
) -> list[StoreCandidate]:
    """Remove candidates already processed for this tenant.

    Matches on google_place_id against existing StoreCandidate DB rows.
    Call this BEFORE passing candidates to the scoring pipeline.

    Args:
        tenant_id:  Tenant scope — never mixes data across tenants.
        candidates: Full list of candidates from the discovery phase.
        db:         Async DB session.

    Returns:
        Subset of *candidates* whose place_id is not yet in the DB.
    """
    if not candidates:
        return []

    from app.models.campaign import StoreCandidate as StoreCandidateRecord

    place_ids = {c.place_id for c in candidates if c.place_id}
    if not place_ids:
        return candidates

    result = await db.execute(
        select(StoreCandidateRecord.google_place_id).where(
            StoreCandidateRecord.tenant_id == tenant_id,
            StoreCandidateRecord.google_place_id.in_(place_ids),
        )
    )
    existing_ids: set[str] = {row[0] for row in result.fetchall() if row[0]}

    deduped = [c for c in candidates if c.place_id not in existing_ids]
    removed = len(candidates) - len(deduped)

    logger.info(
        "store_dedup_complete",
        tenant_id=str(tenant_id),
        original=len(candidates),
        removed=removed,
        remaining=len(deduped),
    )
    return deduped
