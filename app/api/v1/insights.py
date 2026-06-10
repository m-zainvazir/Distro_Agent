"""'Brands like yours' endpoint — anonymized Qdrant similarity insights."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_current_tenant
from app.models.campaign import Tenant
from app.services.similarity_service import SimilarBrand, find_similar_brands
from pydantic import BaseModel

router = APIRouter(prefix="/insights", tags=["insights"])


class SimilarBrandsResponse(BaseModel):
    brand_id: str
    similar_brands: list[SimilarBrand]
    total_found: int


@router.get("/similar-brands", response_model=SimilarBrandsResponse)
async def get_similar_brands(
    brand_id: uuid.UUID,
    k: int = Query(default=5, ge=1, le=20),
    tenant: Annotated[Tenant, Depends(get_current_tenant)] = ...,
) -> SimilarBrandsResponse:
    """Return anonymized aggregates of brands similar to yours.

    Results are cosine-similarity ranked and contain NO competitor PII —
    no brand names, no store lists, no contact information.
    """
    try:
        similar = await find_similar_brands(
            tenant_id=uuid.UUID(str(tenant.id)),
            brand_id=brand_id,
            k=k,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SimilarBrandsResponse(
        brand_id=str(brand_id),
        similar_brands=similar,
        total_found=len(similar),
    )
