"""Tests for provision_sending_domain and its helpers (Layer 20)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.domain_service import (
    _configure_dns_records,
    _generate_domain_candidates,
    _guard_primary_domain,
    _verify_spf_propagated,
    provision_sending_domain,
)
from app.tools.domain_registrar import DomainRegistrarError


# ---------------------------------------------------------------------------
# _generate_domain_candidates
# ---------------------------------------------------------------------------


def test_generate_domain_candidates_slugifies() -> None:
    candidates = _generate_domain_candidates("Acme Corp!")
    assert all("acmecorp" in c for c in candidates)


def test_generate_domain_candidates_strips_special_chars() -> None:
    candidates = _generate_domain_candidates("O'Brien & Sons")
    assert all("obrien" in c for c in candidates)
    assert all("'" not in c and "&" not in c and " " not in c for c in candidates)


def test_generate_domain_candidates_four_results() -> None:
    candidates = _generate_domain_candidates("Beauty")
    assert len(candidates) == 4


def test_generate_domain_candidates_includes_try_prefix() -> None:
    candidates = _generate_domain_candidates("Beauty")
    assert "trybeauty.com" in candidates


def test_generate_domain_candidates_includes_wholesale_suffix() -> None:
    candidates = _generate_domain_candidates("Beauty")
    assert "beautywholesale.com" in candidates


# ---------------------------------------------------------------------------
# _guard_primary_domain
# ---------------------------------------------------------------------------


def test_guard_primary_domain_raises_for_primary() -> None:
    with pytest.raises(ValueError, match="primary domain"):
        _guard_primary_domain("beauty.com", "Beauty")


def test_guard_primary_domain_allows_secondary() -> None:
    _guard_primary_domain("trybeauty.com", "Beauty")  # should not raise


def test_guard_primary_domain_case_insensitive() -> None:
    with pytest.raises(ValueError):
        _guard_primary_domain("acme.com", "ACME")


def test_guard_primary_domain_slugifies_brand() -> None:
    with pytest.raises(ValueError):
        _guard_primary_domain("obrien.com", "O'Brien")


# ---------------------------------------------------------------------------
# _configure_dns_records
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_cf_client() -> AsyncMock:
    client = AsyncMock()
    client.create_dns_record = AsyncMock(return_value={"id": "abc123"})
    client.get_dns_records = AsyncMock(return_value=[])
    return client


@pytest.mark.asyncio
async def test_configure_dns_records_creates_spf(mock_cf_client: AsyncMock) -> None:
    await _configure_dns_records(mock_cf_client, "zone1", "trybeauty.com")
    calls = [str(c) for c in mock_cf_client.create_dns_record.call_args_list]
    spf_call = any("v=spf1" in c for c in calls)
    assert spf_call


@pytest.mark.asyncio
async def test_configure_dns_records_creates_dmarc_p_none(mock_cf_client: AsyncMock) -> None:
    await _configure_dns_records(mock_cf_client, "zone1", "trybeauty.com")
    calls = [str(c) for c in mock_cf_client.create_dns_record.call_args_list]
    dmarc_call = any("p=none" in c for c in calls)
    assert dmarc_call


@pytest.mark.asyncio
async def test_configure_dns_records_no_dkim_without_uid(mock_cf_client: AsyncMock) -> None:
    with patch("app.services.domain_service.settings") as mock_settings:
        mock_settings.sendgrid_domain_auth_uid = ""
        mock_settings.domain_name_templates = "try{brand}.com"
        await _configure_dns_records(mock_cf_client, "zone1", "trybeauty.com")
    cname_calls = [
        c for c in mock_cf_client.create_dns_record.call_args_list if "CNAME" in str(c)
    ]
    assert len(cname_calls) == 0


@pytest.mark.asyncio
async def test_configure_dns_records_two_dkim_with_uid(mock_cf_client: AsyncMock) -> None:
    with patch("app.services.domain_service.settings") as mock_settings:
        mock_settings.sendgrid_domain_auth_uid = "12345"
        mock_settings.domain_name_templates = "try{brand}.com"
        await _configure_dns_records(mock_cf_client, "zone1", "trybeauty.com")
    cname_calls = [
        c for c in mock_cf_client.create_dns_record.call_args_list if "CNAME" in str(c)
    ]
    assert len(cname_calls) == 2


# ---------------------------------------------------------------------------
# _verify_spf_propagated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_spf_found(mock_cf_client: AsyncMock) -> None:
    mock_cf_client.get_dns_records = AsyncMock(
        return_value=[{"content": "v=spf1 include:sendgrid.net ~all"}]
    )
    result = await _verify_spf_propagated(mock_cf_client, "zone1", "trybeauty.com")
    assert result is True


@pytest.mark.asyncio
async def test_verify_spf_not_found(mock_cf_client: AsyncMock) -> None:
    mock_cf_client.get_dns_records = AsyncMock(return_value=[])
    result = await _verify_spf_propagated(mock_cf_client, "zone1", "trybeauty.com")
    assert result is False


@pytest.mark.asyncio
async def test_verify_spf_wrong_content(mock_cf_client: AsyncMock) -> None:
    mock_cf_client.get_dns_records = AsyncMock(
        return_value=[{"content": "some other txt record"}]
    )
    result = await _verify_spf_propagated(mock_cf_client, "zone1", "trybeauty.com")
    assert result is False


# ---------------------------------------------------------------------------
# provision_sending_domain
# ---------------------------------------------------------------------------


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_provision_happy_path_dns_verified() -> None:
    tenant_id = uuid.uuid4()
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.get_zone_id = AsyncMock(return_value=None)
    mock_client.ensure_zone = AsyncMock(return_value="zone-abc")
    mock_client.create_dns_record = AsyncMock(return_value={"id": "rec1"})
    mock_client.get_dns_records = AsyncMock(
        return_value=[{"content": "v=spf1 include:sendgrid.net ~all"}]
    )

    with patch("app.services.domain_service.CloudflareDNSClient", return_value=mock_client):
        domain = await provision_sending_domain(tenant_id, "Beauty", db)

    assert domain.provisioning_status == "dns_verified"
    assert domain.dns_verified_at is not None
    assert domain.warmup_day == 1
    assert domain.is_active is True
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_provision_happy_path_dns_configured_when_spf_not_visible() -> None:
    tenant_id = uuid.uuid4()
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.ensure_zone = AsyncMock(return_value="zone-abc")
    mock_client.create_dns_record = AsyncMock(return_value={"id": "rec1"})
    mock_client.get_dns_records = AsyncMock(return_value=[])

    with patch("app.services.domain_service.CloudflareDNSClient", return_value=mock_client):
        domain = await provision_sending_domain(tenant_id, "Beauty", db)

    assert domain.provisioning_status == "dns_configured"
    assert domain.dns_verified_at is None


@pytest.mark.asyncio
async def test_provision_skips_primary_domain_and_uses_next_candidate() -> None:
    tenant_id = uuid.uuid4()
    db = _make_db()

    # Patch domain_name_templates to put primary first, then a valid secondary
    mock_client = AsyncMock()
    mock_client.ensure_zone = AsyncMock(return_value="zone-xyz")
    mock_client.create_dns_record = AsyncMock(return_value={})
    mock_client.get_dns_records = AsyncMock(return_value=[])

    with (
        patch("app.services.domain_service.CloudflareDNSClient", return_value=mock_client),
        patch("app.services.domain_service.settings") as mock_settings,
    ):
        mock_settings.sendgrid_domain_auth_uid = ""
        # First template would be the primary domain (beauty.com), second is valid
        mock_settings.domain_name_templates = "{brand}.com,try{brand}.com"
        domain = await provision_sending_domain(tenant_id, "Beauty", db)

    assert domain.domain != "beauty.com"
    assert domain.domain == "trybeauty.com"


@pytest.mark.asyncio
async def test_provision_raises_when_all_zones_fail() -> None:
    tenant_id = uuid.uuid4()
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.ensure_zone = AsyncMock(side_effect=DomainRegistrarError("bad credentials"))

    with (
        patch("app.services.domain_service.CloudflareDNSClient", return_value=mock_client),
        pytest.raises(DomainRegistrarError, match="Could not provision"),
    ):
        await provision_sending_domain(tenant_id, "Acme", db)

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_provision_uses_brand_slug_in_domain() -> None:
    tenant_id = uuid.uuid4()
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.ensure_zone = AsyncMock(return_value="zone-abc")
    mock_client.create_dns_record = AsyncMock(return_value={})
    mock_client.get_dns_records = AsyncMock(return_value=[])

    with patch("app.services.domain_service.CloudflareDNSClient", return_value=mock_client):
        domain = await provision_sending_domain(tenant_id, "Beauty Brands Co.", db)

    assert "beautybrandsco" in domain.domain


@pytest.mark.asyncio
async def test_provision_commits_and_refreshes_domain() -> None:
    tenant_id = uuid.uuid4()
    db = _make_db()

    mock_client = AsyncMock()
    mock_client.ensure_zone = AsyncMock(return_value="zone-abc")
    mock_client.create_dns_record = AsyncMock(return_value={})
    mock_client.get_dns_records = AsyncMock(return_value=[])

    with patch("app.services.domain_service.CloudflareDNSClient", return_value=mock_client):
        await provision_sending_domain(tenant_id, "Beauty", db)

    db.commit.assert_awaited()
    db.refresh.assert_awaited()
