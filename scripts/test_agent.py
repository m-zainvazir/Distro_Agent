"""Manual integration test — invokes the agent against a real Shopify store."""
import asyncio
import time

from app.services.brand_service import extract_brand

_TEST_CASES = [
    ("https://gymshark.com", "aesthetic_beauty"),
    ("https://www.etsy.com/shop/ThreeBirdNest", "home_goods"),
]


async def main() -> None:
    for url, vertical in _TEST_CASES:
        print(f"\n{'='*60}")
        print(f"Testing: {url}")
        start = time.perf_counter()
        try:
            profile = await extract_brand(brand_url=url, vertical_tag=vertical)
            elapsed = time.perf_counter() - start
            print(f"  brand_name:              {profile.brand_name}")
            print(f"  product_categories:      {profile.product_categories}")
            print(f"  price_range:             {profile.price_range}")
            print(f"  wholesale_readiness:     {profile.wholesale_readiness_score}")
            print(f"  embedding_vector length: {len(profile.embedding_vector)}")
            print(f"  elapsed:                 {elapsed:.1f}s")
            assert profile.brand_name, "brand_name is empty"
            assert len(profile.embedding_vector) == 384, "wrong embedding size"
            assert elapsed < 60, f"took {elapsed:.1f}s — exceeded 60s budget"
            print("  PASS")
        except Exception as exc:
            print(f"  FAIL: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
