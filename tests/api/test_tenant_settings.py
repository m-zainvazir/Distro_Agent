"""PATCH /tenant/autonomy-mode — validation + persistence (DB mocked)."""
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.tenant import router as tenant_router
from app.core.database import get_db
from app.core.dependencies import get_current_tenant
from app.models.campaign import Tenant

_test_app = FastAPI()
_test_app.include_router(tenant_router, prefix="/api/v1")


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_patch_autonomy_mode_valid_updates_tenant() -> None:
    tenant = Tenant(id=uuid.uuid4(), name="Acme", autonomy_mode="assist")
    db = _make_mock_db()

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    async def _override_tenant() -> Tenant:
        return tenant

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_tenant] = _override_tenant
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/tenant/autonomy-mode", json={"autonomy_mode": "full_auto"}
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["autonomy_mode"] == "full_auto"
    assert tenant.autonomy_mode == "full_auto"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_autonomy_mode_invalid_returns_422() -> None:
    tenant = Tenant(id=uuid.uuid4(), name="Acme", autonomy_mode="assist")
    db = _make_mock_db()

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    async def _override_tenant() -> Tenant:
        return tenant

    _test_app.dependency_overrides[get_db] = _override_db
    _test_app.dependency_overrides[get_current_tenant] = _override_tenant
    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/tenant/autonomy-mode", json={"autonomy_mode": "bogus"}
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 422
    # Tenant left untouched on validation failure.
    assert tenant.autonomy_mode == "assist"
    db.commit.assert_not_awaited()
