$script = @'
import asyncio
from app.models.brand_profile import BrandProfile
from app.models.store_candidate import StoreCandidate
from app.services.analyst_service import score_stores

BRAND = BrandProfile(
    brand_name="Bloom & Co", tagline="Nature beauty",
    primary_colors=["#F5E6D3"], aesthetic_keywords=["botanical","minimal","earthy","clean beauty","skincare"],
    product_categories=["skincare","candles","body care"], price_range=(18.0, 85.0),
    brand_voice_description="Warm and grounded.", wholesale_readiness_score=7.5,
    raw_product_images=[], embedding_vector=[]
)

store = StoreCandidate(
    place_id="t1", name="Botanica Studio", address="1 Main St", city="Brooklyn", state="NY",
    google_categories=["skincare","boutique","beauty","candles","minimal"],
    website_url=None, instagram_handle="@botanica", instagram_followers=8000,
    instagram_posts_last_30_days=10, storefront_image_urls=[], price_tier="$$",
    review_snippets=["curated skincare","independent brands","botanical"]
)

results = asyncio.run(score_stores(BRAND, [store]))
s = results[0]
print(f"vision_was_run: {s.vision_was_run}")
print(f"final_score: {s.final_score}")
print(f"outreach_priority: {s.outreach_priority}")
'@

python -c "$script"