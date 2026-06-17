"""Cloudflare DNS client for automated secondary-domain provisioning (Layer 20).

Handles zone management and DNS record creation (SPF / DKIM / DMARC).
All credentials are sourced from ``settings`` — never hardcoded.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger

_CF_API_BASE = "https://api.cloudflare.com/client/v4"
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0  # seconds; doubles each attempt


class DomainRegistrarError(Exception):
    """Raised when the registrar/DNS API returns an unrecoverable error."""


class CloudflareDNSClient:
    """Async Cloudflare DNS client — zone management + DNS record creation.

    Creating a zone does **not** purchase the domain; it enables Cloudflare DNS
    management. The domain must be registered with any registrar that supports
    custom nameservers, or via Cloudflare Registrar itself.
    """

    def __init__(self) -> None:
        self._token = settings.cloudflare_api_token
        self._account_id = settings.cloudflare_account_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute an authenticated Cloudflare API request with retry/backoff."""
        url = f"{_CF_API_BASE}{path}"
        last_exc: Exception | None = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    resp = await client.request(
                        method,
                        url,
                        json=payload,
                        params=params,
                        headers=self._headers(),
                    )
                    if resp.status_code >= 500:
                        logger.warning(
                            "cloudflare_api_5xx",
                            attempt=attempt,
                            status=resp.status_code,
                            body=resp.text[:200],
                        )
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(_RETRY_BACKOFF * (2 ** (attempt - 1)))
                        continue
                    body: dict[str, Any] = resp.json()
                    if not body.get("success", False):
                        errs = body.get("errors", [])
                        raise DomainRegistrarError(f"Cloudflare API error: {errs}")
                    return body
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_exc = exc
                    logger.warning(
                        "cloudflare_transport_error",
                        attempt=attempt,
                        error=str(exc),
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_BACKOFF * (2 ** (attempt - 1)))

        if last_exc is not None:
            raise last_exc
        raise DomainRegistrarError("All retries exhausted with no successful response")

    # ------------------------------------------------------------------
    # Zone management
    # ------------------------------------------------------------------

    async def get_zone_id(self, domain: str) -> str | None:
        """Return the Cloudflare zone ID for *domain*, or ``None`` if not found."""
        try:
            body = await self._request("GET", "/zones", params={"name": domain})
            zones: list[dict[str, Any]] = body.get("result", [])
            return zones[0]["id"] if zones else None
        except DomainRegistrarError:
            return None

    async def ensure_zone(self, domain: str) -> str:
        """Return the zone ID for *domain*, creating a Cloudflare zone if needed."""
        existing = await self.get_zone_id(domain)
        if existing:
            logger.info("cloudflare_zone_found", domain=domain, zone_id=existing)
            return existing

        body = await self._request(
            "POST",
            "/zones",
            payload={
                "name": domain,
                "account": {"id": self._account_id},
                "jump_start": False,
            },
        )
        zone_id: str = body["result"]["id"]
        logger.info("cloudflare_zone_created", domain=domain, zone_id=zone_id)
        return zone_id

    # ------------------------------------------------------------------
    # DNS records
    # ------------------------------------------------------------------

    async def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int = 1,
    ) -> dict[str, Any]:
        """Create a DNS record and return the Cloudflare result object."""
        body = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            payload={
                "type": record_type,
                "name": name,
                "content": content,
                "ttl": ttl,
            },
        )
        result: dict[str, Any] = body.get("result", {})
        logger.info(
            "dns_record_created",
            zone_id=zone_id,
            record_type=record_type,
            name=name,
        )
        return result

    async def get_dns_records(
        self,
        zone_id: str,
        record_type: str,
        name: str,
    ) -> list[dict[str, Any]]:
        """Return DNS records matching *record_type* and *name* (empty list on error)."""
        try:
            body = await self._request(
                "GET",
                f"/zones/{zone_id}/dns_records",
                params={"type": record_type, "name": name},
            )
            return body.get("result", [])
        except DomainRegistrarError:
            return []
