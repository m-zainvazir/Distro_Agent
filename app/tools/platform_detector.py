import httpx


async def detect_platform(url: str) -> str:
    """Return 'shopify' or 'etsy'; raise UnsupportedPlatformError otherwise."""
    normalized = url.rstrip("/").lower()

    if "etsy.com/shop/" in normalized:
        return "etsy"

    if "myshopify.com" in normalized:
        return "shopify"

    # Probe for Shopify /products.json
    base = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{base}/products.json?limit=1")
            if resp.status_code == 200:
                data = resp.json()
                if "products" in data:
                    return "shopify"
    except (httpx.HTTPError, ValueError):
        pass

    return "generic"
