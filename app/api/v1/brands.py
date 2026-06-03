import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import BrandExtractionError, UnsupportedPlatformError
from app.models.brand_profile import BrandProfile
from app.services.brand_service import (
    extract_brand,
    save_brand_profile_record,
    upsert_brand_embedding,
)

router = APIRouter(prefix="/brands", tags=["brands"])


class ExtractRequest(BaseModel):
    brand_url: str = ""
    brand_name: str = ""
    vertical_tag: str
    tenant_id: uuid.UUID

    @model_validator(mode="after")
    def require_url_or_name(self) -> "ExtractRequest":
        if not self.brand_url and not self.brand_name:
            raise ValueError("Provide either brand_url or brand_name")
        return self


class ExtractResponse(BaseModel):
    status: str
    brand_profile_id: str
    brand_profile: BrandProfile


@router.post("/extract", response_model=ExtractResponse)
async def extract_brand_endpoint(
    body: ExtractRequest,
    db: AsyncSession = Depends(get_db),
) -> ExtractResponse:
    try:
        profile = await extract_brand(
            brand_url=body.brand_url,
            vertical_tag=body.vertical_tag,
            brand_name=body.brand_name,
        )
    except UnsupportedPlatformError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "UNSUPPORTED_PLATFORM", "message": str(exc)},
        ) from exc
    except BrandExtractionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EXTRACTION_FAILED",
                "message": str(exc),
                "retry_suggestion": exc.retry_suggestion,
            },
        ) from exc

    record = await save_brand_profile_record(db, body.tenant_id, body.brand_url, profile)
    await upsert_brand_embedding(record.id, body.tenant_id, profile)  # type: ignore[arg-type]

    return ExtractResponse(
        status="ok",
        brand_profile_id=str(record.id),
        brand_profile=profile,
    )
