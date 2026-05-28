from pydantic import BaseModel, ConfigDict


class BrandProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    brand_name: str
    tagline: str
    primary_colors: list[str]
    aesthetic_keywords: list[str]
    product_categories: list[str]
    price_range: tuple[float, float]
    brand_voice_description: str
    wholesale_readiness_score: float
    raw_product_images: list[str]
    embedding_vector: list[float]
