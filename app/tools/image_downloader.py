import base64

import httpx

from app.core.logging import logger

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DistroAgent/1.0; +https://distroagent.com/bot)"
    )
}


async def download_images(image_urls: list[str], max_images: int = 5) -> list[str]:
    """Download up to max_images images and return them as base64 strings."""
    results: list[str] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=_HEADERS) as client:
        for url in image_urls[:max_images]:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                encoded = base64.b64encode(resp.content).decode("utf-8")
                results.append(encoded)
            except httpx.HTTPError:
                logger.warning("image_download_failed", url=url)
    return results
