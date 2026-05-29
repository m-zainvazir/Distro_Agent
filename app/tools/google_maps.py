import asyncio

import httpx

from app.core.errors import BrandExtractionError
from app.core.logging import logger

# Places API (New) endpoints
_TEXTSEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

_SEARCH_FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.types,places.rating,places.userRatingCount"
_DETAILS_FIELD_MASK = "id,websiteUri,internationalPhoneNumber,currentOpeningHours,businessStatus"


async def search_places(query: str, location: str, api_key: str) -> list[dict]:
    """Text search via Places API (New).

    Returns a list of place dicts with keys:
    place_id, name, formatted_address, types, rating, user_ratings_total.
    Handles HTTP 429 rate limit by sleeping 2s and retrying once.
    Raises BrandExtractionError on permanent failures.
    """
    payload = {"textQuery": f"{query} near {location}"}
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _SEARCH_FIELD_MASK,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(2):
            try:
                response = await client.post(_TEXTSEARCH_URL, json=payload, headers=headers)
            except httpx.RequestError as exc:
                raise BrandExtractionError(
                    message=f"Google Maps request failed: {exc}",
                    retry_suggestion="Check network connectivity.",
                ) from exc

            if response.status_code == 429 and attempt == 0:
                logger.warning("google_maps_rate_limit", query=query, attempt=attempt)
                await asyncio.sleep(2.0)
                continue

            if response.status_code != 200:
                raise BrandExtractionError(
                    message=f"Google Maps API error: HTTP {response.status_code} — {response.text[:300]}",
                    retry_suggestion="Verify your API key and that 'Places API (New)' is enabled in Google Cloud Console.",
                )

            raw_places: list[dict] = response.json().get("places", [])

            # Normalize new API field names to match what the rest of the codebase expects
            places = [
                {
                    "place_id": p.get("id", ""),
                    "name": p.get("displayName", {}).get("text", ""),
                    "formatted_address": p.get("formattedAddress", ""),
                    "types": p.get("types", []),
                    "rating": p.get("rating"),
                    "user_ratings_total": p.get("userRatingCount"),
                }
                for p in raw_places
            ]

            logger.info("google_maps_search", query=query, location=location, result_count=len(places))
            return places

    raise BrandExtractionError(
        message="Google Maps API rate limit exceeded after retry.",
        retry_suggestion="Wait and retry, or reduce query frequency.",
    )


async def get_place_details(place_id: str, api_key: str) -> dict:
    """Places Details API (New).

    Returns a dict with website, formatted_phone_number, opening_hours,
    business_status. Handles HTTP 429 rate limit by sleeping 2s and retrying once.
    Raises BrandExtractionError on permanent failures.
    """
    url = _DETAILS_URL.format(place_id=place_id)
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _DETAILS_FIELD_MASK,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(2):
            try:
                response = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                raise BrandExtractionError(
                    message=f"Google Maps Details request failed: {exc}",
                    retry_suggestion="Check network connectivity.",
                ) from exc

            if response.status_code == 429 and attempt == 0:
                logger.warning("google_maps_details_rate_limit", place_id=place_id, attempt=attempt)
                await asyncio.sleep(2.0)
                continue

            if response.status_code != 200:
                raise BrandExtractionError(
                    message=f"Google Maps Details API error: HTTP {response.status_code} — {response.text[:300]}",
                    retry_suggestion="Verify your API key and place_id.",
                )

            data = response.json()

            # Normalize new API field names to match what the rest of the codebase expects
            return {
                "website": data.get("websiteUri", ""),
                "formatted_phone_number": data.get("internationalPhoneNumber", ""),
                "opening_hours": data.get("currentOpeningHours", {}),
                "business_status": data.get("businessStatus", ""),
            }

    raise BrandExtractionError(
        message=f"Google Maps Details rate limit exceeded for place_id={place_id}.",
        retry_suggestion="Wait and retry, or reduce query frequency.",
    )
