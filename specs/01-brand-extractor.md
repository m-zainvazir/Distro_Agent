# Spec: Brand Intelligence Extractor

## Overview
Given a Shopify, Etsy, or brand URL, extract a structured brand profile including products, aesthetics, pricing, and positioning within 60 seconds.

## Inputs
- brand_url: str — A Shopify storefront URL or Etsy shop URL
- vertical_tag: str — e.g., "aesthetic_beauty", "home_goods", "pet_products"

## Outputs
- BrandProfile (Pydantic model):
  - brand_name: str
  - tagline: str
  - primary_colors: list[str]  # hex codes from images
  - aesthetic_keywords: list[str]  # e.g., ["minimalist", "clean", "botanical"]
  - product_categories: list[str]
  - price_range: tuple[float, float]  # min, max in USD
  - brand_voice_description: str  # 2-3 sentence description
  - wholesale_readiness_score: float  # 0-10, how ready for wholesale
  - raw_product_images: list[str]  # URLs of product images
  - embedding_vector: list[float]  # 1536-dim embedding

## Behavior
### Happy Path
1. Fetch the URL with httpx (handle Shopify /products.json endpoint)
2. Extract product catalog, pricing, about page content
3. Download 3-5 representative product images
4. Send images + text to Claude claude-sonnet-4-20250514 (vision) for aesthetic analysis
5. Generate text embedding with OpenAI text-embedding-3-small
6. Return BrandProfile

### Error Cases
- URL unreachable → raise BrandExtractionError with retry suggestion
- Not a Shopify/Etsy URL → raise UnsupportedPlatformError
- No products found → return partial profile with low wholesale_readiness_score
- Image download fails → proceed with text-only analysis

## Acceptance Criteria
- [ ] Extracts data from shopify.com URLs in < 30 seconds
- [ ] Extracts data from etsy.com shop URLs in < 30 seconds
- [ ] Returns valid BrandProfile with all fields populated
- [ ] Test with known Shopify store: verify name and categories are correct
- [ ] Test error case: invalid URL raises BrandExtractionError
- [ ] Token usage logged per extraction run