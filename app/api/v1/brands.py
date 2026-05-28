from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from app.core.errors import BrandExtractionError, UnsupportedPlatformError
from app.models.brand_profile import BrandProfile
from app.services.brand_service import extract_brand

router = APIRouter(prefix="/brands", tags=["brands"])


class ExtractRequest(BaseModel):
    brand_url: str = ""
    brand_name: str = ""
    vertical_tag: str

    @model_validator(mode="after")
    def require_url_or_name(self) -> "ExtractRequest":
        if not self.brand_url and not self.brand_name:
            raise ValueError("Provide either brand_url or brand_name")
        return self


@router.post("/extract", response_model=BrandProfile)
async def extract_brand_endpoint(body: ExtractRequest) -> BrandProfile:
    try:
        return await extract_brand(
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
