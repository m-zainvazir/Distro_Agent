from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.core.config import settings
from app.core.errors import BrandExtractionError
from app.core.logging import logger

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DistroAgent/1.0; +https://distroagent.com/bot)"
    )
}

_ETSY_API_BASE = "https://openapi.etsy.com/v3/application"


def _extract_etsy_shop_name(url: str) -> str:
    """Extract shop name from an Etsy shop URL."""
    path = urlparse(url).path.rstrip("/")
    parts = path.split("/")
    try:
        return parts[parts.index("shop") + 1]
    except (ValueError, IndexError) as exc:
        raise BrandExtractionError(
            message=f"Cannot extract Etsy shop name from URL: {url}",
            retry_suggestion="Ensure the URL is in the format etsy.com/shop/ShopName",
        ) from exc


async def fetch_etsy_catalog(url: str) -> tuple[list[dict], str]:
    """Fetch listings and shop info via the Etsy Open API v3."""
    if not settings.etsy_api_key:
        raise BrandExtractionError(
            message="ETSY_API_KEY is not configured",
            retry_suggestion="Add ETSY_API_KEY to your .env file. Register at etsy.com/developers.",
        )

    shop_name = _extract_etsy_shop_name(url)
    headers = {"x-api-key": settings.etsy_api_key}

    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            # Fetch shop info for about text
            shop_resp = await client.get(f"{_ETSY_API_BASE}/shops/{shop_name}")
            shop_resp.raise_for_status()
            shop_data = shop_resp.json()
            about_text = " ".join(
                filter(None, [
                    shop_data.get("title", ""),
                    shop_data.get("announcement", ""),
                    shop_data.get("sale_message", ""),
                ])
            )[:4000]

            # Fetch active listings with images
            listings_resp = await client.get(
                f"{_ETSY_API_BASE}/shops/{shop_name}/listings/active",
                params={"limit": 100, "includes[]": "Images"},
            )
            listings_resp.raise_for_status()
            results = listings_resp.json().get("results", [])

    except httpx.TimeoutException as exc:
        raise BrandExtractionError(
            message=f"Etsy API request timed out for shop '{shop_name}'",
            retry_suggestion="Retry after 30 seconds.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            raise BrandExtractionError(
                message="Etsy API key is invalid or expired",
                retry_suggestion="Check ETSY_API_KEY in your .env file.",
            ) from exc
        if status == 404:
            raise BrandExtractionError(
                message=f"Etsy shop '{shop_name}' not found",
                retry_suggestion="Verify the shop name in the URL is correct.",
            ) from exc
        raise BrandExtractionError(
            message=f"Etsy API returned HTTP {status}",
            retry_suggestion="Check the Etsy developer status page and retry.",
        ) from exc

    products = [
        {
            "title": r.get("title", ""),
            "price": (
                f"{r['price']['amount'] / r['price']['divisor']:.2f} "
                f"{r['price']['currency_code']}"
                if r.get("price")
                else ""
            ),
            "images": [
                {"src": img.get("url_570xN", "")}
                for img in r.get("images", [])
                if img.get("url_570xN")
            ],
        }
        for r in results
    ]

    logger.info("etsy_api_fetch_complete", shop=shop_name, listings=len(products))
    return products, about_text


async def fetch_shopify_catalog(url: str) -> tuple[list[dict], str]:
    base = url.rstrip("/")
    try:
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True, headers=_HEADERS
        ) as client:
            products_resp = await client.get(f"{base}/products.json?limit=250")
            products_resp.raise_for_status()
            products: list[dict] = products_resp.json().get("products", [])

            about_text = ""
            try:
                about_resp = await client.get(f"{base}/pages/about")
                if about_resp.status_code == 200:
                    soup = BeautifulSoup(about_resp.text, "html.parser")
                    about_text = soup.get_text(separator=" ", strip=True)[:4000]
            except httpx.HTTPError:
                logger.warning("shopify_about_fetch_failed", url=base)

    except httpx.TimeoutException as exc:
        raise BrandExtractionError(
            message=f"Request to {url} timed out",
            retry_suggestion="Retry after 30 seconds or check if the store is online.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise BrandExtractionError(
            message=f"HTTP {exc.response.status_code} from {url}",
            retry_suggestion="Verify the store URL is correct and publicly accessible.",
        ) from exc

    return products, about_text


async def scrape_with_playwright(url: str) -> tuple[list[dict], str]:
    """Render a page with a real browser and extract products + about text.

    Works on Etsy, generic brand sites, and any JS-rendered storefront.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = await context.new_page()
            # Mask navigator.webdriver so bot-detection scripts don't flag us
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            await page.goto(url, wait_until="networkidle", timeout=30000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Guard: if the page returned is a bot-challenge/blank page, raise early
        page_title = soup.title.string.strip() if soup.title else ""
        domain = urlparse(url).netloc.replace("www.", "")
        if page_title.lower() in ("", domain.lower()):
            raise BrandExtractionError(
                message=f"Bot-detection page served for {url} (title: '{page_title}')",
                retry_suggestion="The site blocked the scraper. Try again later or provide a direct brand_url.",
            )

        # --- Extract products ---
        products: list[dict] = []

        # Etsy listing cards
        for card in soup.select("div[data-listing-id]")[:50]:
            title_el = card.select_one("h3,h2,[data-listing-title]")
            price_el = card.select_one(
                "[data-currency-value],[data-buy-box-region] .currency-value"
            )
            img_el = card.select_one("img")
            products.append(
                {
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "price": price_el.get_text(strip=True) if price_el else "",
                    "image": img_el.get("src", "") if img_el else "",
                }
            )

        # Generic product cards — headings near a price-like string
        if not products:
            import re
            price_re = re.compile(r"\$[\d,]+(\.\d{2})?")
            for heading in soup.select("h2, h3")[:50]:
                parent = heading.parent
                price_text = ""
                if parent:
                    price_match = price_re.search(parent.get_text())
                    price_text = price_match.group(0) if price_match else ""
                img_el = heading.find("img") or (parent.find("img") if parent else None)
                products.append(
                    {
                        "title": heading.get_text(strip=True),
                        "price": price_text,
                        "image": img_el.get("src", "") if img_el else "",
                    }
                )

        # --- Extract about text ---
        about_text = ""
        for selector in [
            "#about-section",
            "[data-about-section]",
            "#about",
            "[class*=about]",
        ]:
            el = soup.select_one(selector)
            if el:
                about_text = el.get_text(separator=" ", strip=True)[:4000]
                break

        if not about_text:
            meta = soup.select_one('meta[name="description"]')
            if meta:
                about_text = meta.get("content", "")[:4000]

        logger.info("playwright_scrape_complete", url=url, products_found=len(products))
        return products, about_text

    except Exception as exc:
        raise BrandExtractionError(
            message=f"Playwright scrape failed for {url}: {exc}",
            retry_suggestion="Check the URL is publicly accessible and try again.",
        ) from exc
