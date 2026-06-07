from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import BrandExtractionError
from app.models.brand_profile import BrandProfile
from app.services.brand_service import extract_brand

# Patch targets — must match the import location inside brand_extractor.py
_DETECT = "app.agents.brand_extractor.detect_platform"
_FETCH_SHOPIFY = "app.agents.brand_extractor.fetch_shopify_catalog"
_FETCH_ETSY = "app.agents.brand_extractor.fetch_etsy_catalog"
_PLAYWRIGHT = "app.agents.brand_extractor.scrape_with_playwright"
_DOWNLOAD = "app.agents.brand_extractor.download_images"
_COLORS = "app.agents.brand_extractor.extract_colors_from_images"
_ANALYZE = "app.agents.brand_extractor.analyze_brand_aesthetics"
_EMBED = "app.agents.brand_extractor.generate_brand_embedding"
_DISCOVER = "app.agents.brand_extractor.discover_brand_url"

_FAKE_ANALYSIS = {
    "brand_name": "Bloom & Co",
    "tagline": "Nature-inspired beauty",
    "aesthetic_keywords": ["botanical", "minimal", "earthy"],
    "product_categories": ["skincare", "candles"],
    "price_range_min": 12.0,
    "price_range_max": 85.0,
    "brand_voice_description": "Warm and grounded. Speaks to the eco-conscious consumer.",
    "wholesale_readiness_score": 7.5,
}

_FAKE_PRODUCTS_SHOPIFY = [
    {
        "title": "Rose Face Serum",
        "variants": [{"price": "45.00"}],
        "images": [{"src": "https://cdn.shopify.com/img1.jpg"}],
    }
]

_FAKE_PRODUCTS_GENERIC = [
    {"title": "Beeswax Candle", "price": "$18", "image": "https://i.etsy.com/img1.jpg"}
]

_FAKE_EMBEDDING = [0.1] * 384  # bge-small-en-v1.5 produces 384-dim vectors
_FAKE_COLORS = ["#F5E6D3", "#2C4A2E", "#FFFFFF"]


@pytest.mark.asyncio
async def test_shopify_happy_path():
    with (
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(return_value=(_FAKE_PRODUCTS_SHOPIFY, "Botanical beauty brand.", "Bloom & Co")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=["base64imagedata=="])),
        patch(_COLORS, return_value=_FAKE_COLORS),
        patch(
            _ANALYZE,
            new=AsyncMock(
                return_value=(_FAKE_ANALYSIS, {"input_tokens": 500, "output_tokens": 200})
            ),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="https://teststore.myshopify.com",
            vertical_tag="aesthetic_beauty",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.brand_name == "Bloom & Co"
    assert len(profile.product_categories) > 0
    assert profile.price_range[0] < profile.price_range[1]
    assert len(profile.embedding_vector) == 384
    assert profile.primary_colors == _FAKE_COLORS


@pytest.mark.asyncio
async def test_etsy_api_happy_path():
    etsy_products = [
        {
            "title": "Beeswax Candle Set",
            "price": "18.00 USD",
            "images": [{"src": "https://i.etsy.com/img1.jpg"}],
        }
    ]
    with (
        patch(_DETECT, new=AsyncMock(return_value="etsy")),
        patch(
            _FETCH_ETSY,
            new=AsyncMock(return_value=(etsy_products, "Handmade candles from beeswax.", "BloominCo")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=["base64imagedata=="])),
        patch(_COLORS, return_value=_FAKE_COLORS),
        patch(
            _ANALYZE,
            new=AsyncMock(
                return_value=(_FAKE_ANALYSIS, {"input_tokens": 300, "output_tokens": 150})
            ),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="https://www.etsy.com/shop/BloominCo",
            vertical_tag="home_goods",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.brand_name == "BloominCo"   # canonical_name from Etsy API wins
    assert len(profile.embedding_vector) == 384


@pytest.mark.asyncio
async def test_etsy_missing_api_key_raises():
    with (
        patch(_DETECT, new=AsyncMock(return_value="etsy")),
        patch(
            _FETCH_ETSY,
            new=AsyncMock(
                side_effect=BrandExtractionError(
                    message="ETSY_API_KEY is not configured",
                    retry_suggestion="Add ETSY_API_KEY to your .env file.",
                )
            ),
        ),
    ):
        with pytest.raises(BrandExtractionError) as exc_info:
            await extract_brand(
                brand_url="https://www.etsy.com/shop/BloominCo",
                vertical_tag="home_goods",
            )
        assert "ETSY_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generic_url_scrape():
    with (
        patch(_DETECT, new=AsyncMock(return_value="generic")),
        patch(
            _PLAYWRIGHT,
            new=AsyncMock(return_value=(_FAKE_PRODUCTS_GENERIC, "A generic brand website.", "Bloom & Co")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=["base64imagedata=="])),
        patch(_COLORS, return_value=[]),
        patch(
            _ANALYZE,
            new=AsyncMock(
                return_value=(_FAKE_ANALYSIS, {"input_tokens": 300, "output_tokens": 100})
            ),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="https://somerandombrand.com",
            vertical_tag="home_goods",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.brand_name == "Bloom & Co"


@pytest.mark.asyncio
async def test_brand_name_discovery():
    with (
        patch(
            _DISCOVER,
            new=AsyncMock(return_value="https://teststore.myshopify.com"),
        ),
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(return_value=(_FAKE_PRODUCTS_SHOPIFY, "Botanical beauty brand.", "Bloom & Co")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=["base64imagedata=="])),
        patch(_COLORS, return_value=_FAKE_COLORS),
        patch(
            _ANALYZE,
            new=AsyncMock(
                return_value=(_FAKE_ANALYSIS, {"input_tokens": 400, "output_tokens": 180})
            ),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="",
            vertical_tag="aesthetic_beauty",
            brand_name="Bloom Co",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.brand_name == "Bloom & Co"


@pytest.mark.asyncio
async def test_discovery_fails():
    with patch(
        _DISCOVER,
        new=AsyncMock(
            side_effect=BrandExtractionError(
                message="Could not find a store URL for brand 'FakeBrand'",
                retry_suggestion="Provide brand_url directly.",
            )
        ),
    ):
        with pytest.raises(BrandExtractionError):
            await extract_brand(
                brand_url="",
                vertical_tag="home_goods",
                brand_name="FakeBrand",
            )


@pytest.mark.asyncio
async def test_unknown_url_uses_generic_scraper():
    """Non-Shopify/Etsy URLs now route to Playwright generic scraper instead of raising."""
    with (
        patch(_DETECT, new=AsyncMock(return_value="generic")),
        patch(_PLAYWRIGHT, new=AsyncMock(return_value=(_FAKE_PRODUCTS_GENERIC, "Generic site.", "SomeBrand"))),
        patch(_DOWNLOAD, new=AsyncMock(return_value=["base64imagedata=="])),
        patch(_COLORS, return_value=[]),
        patch(
            _ANALYZE,
            new=AsyncMock(return_value=(_FAKE_ANALYSIS, {"input_tokens": 200, "output_tokens": 100})),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="https://amazon.com",
            vertical_tag="home_goods",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.brand_name == "SomeBrand"   # canonical_name from og:site_name wins


@pytest.mark.asyncio
async def test_unreachable_url_raises():
    with (
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(
                side_effect=BrandExtractionError(
                    message="Request timed out",
                    retry_suggestion="Retry after 30 seconds.",
                )
            ),
        ),
    ):
        with pytest.raises(BrandExtractionError) as exc_info:
            await extract_brand(
                brand_url="https://unreachable.myshopify.com",
                vertical_tag="home_goods",
            )
        assert exc_info.value.retry_suggestion != ""


@pytest.mark.asyncio
async def test_no_products_partial_profile():
    with (
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(return_value=([], "Some about text.", "")),
        ),
    ):
        profile = await extract_brand(
            brand_url="https://emptystore.myshopify.com",
            vertical_tag="home_goods",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.wholesale_readiness_score == 0.0


@pytest.mark.asyncio
async def test_image_failure_text_only():
    with (
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(return_value=(_FAKE_PRODUCTS_SHOPIFY, "Botanical beauty brand.", "Bloom & Co")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=[])),  # all downloads failed
        patch(_COLORS, return_value=[]),
        patch(
            _ANALYZE,
            new=AsyncMock(
                return_value=(_FAKE_ANALYSIS, {"input_tokens": 200, "output_tokens": 100})
            ),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="https://teststore.myshopify.com",
            vertical_tag="aesthetic_beauty",
        )

    assert isinstance(profile, BrandProfile)
    assert profile.brand_name == "Bloom & Co"
    assert profile.primary_colors == []


@pytest.mark.asyncio
async def test_token_usage_logged():
    captured_usage: dict = {}

    async def fake_analyze(*args, **kwargs):
        usage = {"input_tokens": 500, "output_tokens": 200}
        captured_usage.update(usage)
        return _FAKE_ANALYSIS, usage

    with (
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(return_value=(_FAKE_PRODUCTS_SHOPIFY, "Botanical beauty brand.", "Bloom & Co")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=["base64imagedata=="])),
        patch(_COLORS, return_value=_FAKE_COLORS),
        patch(_ANALYZE, new=AsyncMock(side_effect=fake_analyze)),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        await extract_brand(
            brand_url="https://teststore.myshopify.com",
            vertical_tag="aesthetic_beauty",
        )

    assert captured_usage.get("input_tokens", 0) > 0
    assert captured_usage.get("output_tokens", 0) > 0


@pytest.mark.asyncio
async def test_brand_name_pinned_to_store_name():
    """Reproduce the Allbirds → 'Trino' bug: even when the LLM returns a wrong
    sub-brand name, the canonical store name from platform metadata wins."""
    _allbirds_products = [
        {"title": "Trino Tee", "vendor": "Allbirds", "variants": [{"price": "45.00"}], "images": []},
        {"title": "Tree Runner", "vendor": "Allbirds", "variants": [{"price": "98.00"}], "images": []},
        {"title": "Wool Lounger", "vendor": "Allbirds", "variants": [{"price": "130.00"}], "images": []},
    ]
    # LLM incorrectly infers the brand name from the first product title
    _llm_wrong_analysis = {**_FAKE_ANALYSIS, "brand_name": "Trino"}

    with (
        patch(_DETECT, new=AsyncMock(return_value="shopify")),
        patch(
            _FETCH_SHOPIFY,
            new=AsyncMock(return_value=(_allbirds_products, "Sustainable footwear.", "Allbirds")),
        ),
        patch(_DOWNLOAD, new=AsyncMock(return_value=[])),
        patch(_COLORS, return_value=[]),
        patch(
            _ANALYZE,
            new=AsyncMock(return_value=(_llm_wrong_analysis, {"input_tokens": 300, "output_tokens": 100})),
        ),
        patch(_EMBED, new=AsyncMock(return_value=_FAKE_EMBEDDING)),
    ):
        profile = await extract_brand(
            brand_url="https://allbirds.com",
            vertical_tag="footwear",
        )

    assert profile.brand_name == "Allbirds", (
        f"Expected 'Allbirds' but got '{profile.brand_name}' — "
        "canonical_name from Shopify vendor field must override LLM output"
    )
