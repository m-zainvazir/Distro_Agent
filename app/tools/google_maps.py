import asyncio

import httpx

from app.core.errors import BrandExtractionError
from app.core.logging import logger

_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

_TEXTSEARCH_FIELDS = ["place_id", "name", "formatted_address", "types", "rating", "user_ratings_total"]
_DETAILS_FIELDS = ["website", "formatted_phone_number", "opening_hours", "business_status"]


async def search_places(query: str, location: str, api_key: str) -> list[dict]:
    """Text search via Places API.

    Returns a list of place dicts with keys:
    place_id, name, formatted_address, types, rating, user_ratings_total.
    Handles OVER_QUERY_LIMIT by sleeping 2s and retrying once.
    Raises BrandExtractionError on permanent failures.
    """
    params = {
        "query": f"{query} near {location}",
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(2):
            try:
                response = await client.get(_TEXTSEARCH_URL, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise BrandExtractionError(
                    message=f"Google Maps HTTP error: {exc.response.status_code}",
                    retry_suggestion="Check your Google Maps API key and quota.",
                ) from exc
            except httpx.RequestError as exc:
                raise BrandExtractionError(
                    message=f"Google Maps request failed: {exc}",
                    retry_suggestion="Check network connectivity.",
                ) from exc

            data = response.json()
            status = data.get("status", "")

            if status == "OK":
                results: list[dict] = data.get("results", [])
                logger.info(
                    "google_maps_search",
                    query=query,
                    location=location,
                    result_count=len(results),
                )
                return results

            if status == "ZERO_RESULTS":
                logger.info("google_maps_zero_results", query=query, location=location)
                return []

            if status == "OVER_QUERY_LIMIT" and attempt == 0:
                logger.warning(
                    "google_maps_rate_limit",
                    query=query,
                    attempt=attempt,
                )
                await asyncio.sleep(2.0)
                continue

            # Permanent failure statuses: REQUEST_DENIED, INVALID_REQUEST, etc.
            raise BrandExtractionError(
                message=f"Google Maps API error: status={status}, error_message={data.get('error_message', '')}",
                retry_suggestion="Verify API key permissions and request parameters.",
            )

    # Exhausted retries for OVER_QUERY_LIMIT
    raise BrandExtractionError(
        message="Google Maps API rate limit exceeded after retry.",
        retry_suggestion="Wait and retry, or reduce query frequency.",
    )


async def get_place_details(place_id: str, api_key: str) -> dict:
    """Places Details API.

    Returns a dict with website, formatted_phone_number, opening_hours,
    business_status. Handles OVER_QUERY_LIMIT by sleeping 2s and retrying once.
    Raises BrandExtractionError on permanent failures.
    """
    params = {
        "place_id": place_id,
        "fields": ",".join(_DETAILS_FIELDS),
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(2):
            try:
                response = await client.get(_DETAILS_URL, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise BrandExtractionError(
                    message=f"Google Maps Details HTTP error: {exc.response.status_code}",
                    retry_suggestion="Check your Google Maps API key and quota.",
                ) from exc
            except httpx.RequestError as exc:
                raise BrandExtractionError(
                    message=f"Google Maps Details request failed: {exc}",
                    retry_suggestion="Check network connectivity.",
                ) from exc

            data = response.json()
            status = data.get("status", "")

            if status == "OK":
                result: dict = data.get("result", {})
                logger.info("google_maps_details", place_id=place_id)
                return result

            if status == "OVER_QUERY_LIMIT" and attempt == 0:
                logger.warning(
                    "google_maps_details_rate_limit",
                    place_id=place_id,
                    attempt=attempt,
                )
                await asyncio.sleep(2.0)
                continue

            raise BrandExtractionError(
                message=f"Google Maps Details API error: status={status}, error_message={data.get('error_message', '')}",
                retry_suggestion="Verify API key permissions and place_id.",
            )

    raise BrandExtractionError(
        message=f"Google Maps Details rate limit exceeded for place_id={place_id}.",
        retry_suggestion="Wait and retry, or reduce query frequency.",
    )
