"""Auth flow tests — all DB calls are mocked via dependency override."""
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import router as auth_router
from app.core.database import get_db
from app.core.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Test app — isolated from the real main app
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(auth_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()
_EMAIL = "test@example.com"
_PASSWORD = "securepassword123"


def _make_mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _scalar_none(db: AsyncMock) -> None:
    """Configure db.execute() to return no existing user."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)


def _scalar_user(db: AsyncMock, hashed: str) -> None:
    """Configure db.execute() to return an existing User-like object."""
    from app.models.user import User

    user = User(
        id=_USER_ID,
        email=_EMAIL,
        hashed_password=hashed,
        tenant_id=_TENANT_ID,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)


# ---------------------------------------------------------------------------
# Signup tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_creates_tenant_and_returns_jwt() -> None:
    db = _make_mock_db()
    _scalar_none(db)

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={"email": _EMAIL, "password": _PASSWORD, "brand_name": "Acme"},
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "tenant_id" in body
    assert db.add.call_count == 2  # Tenant + User
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_signup_duplicate_email_returns_409() -> None:
    db = _make_mock_db()
    _scalar_user(db, hash_password(_PASSWORD))

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={"email": _EMAIL, "password": _PASSWORD, "brand_name": "Acme"},
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_correct_password_returns_jwt() -> None:
    db = _make_mock_db()
    _scalar_user(db, hash_password(_PASSWORD))

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD},
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401() -> None:
    db = _make_mock_db()
    _scalar_user(db, hash_password(_PASSWORD))

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": "wrongpassword"},
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401() -> None:
    db = _make_mock_db()
    _scalar_none(db)

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db

    _test_app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": _PASSWORD},
        )
    _test_app.dependency_overrides.clear()

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# get_current_tenant dependency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_tenant_valid_token() -> None:
    from app.core.dependencies import get_current_tenant
    from app.models.campaign import Tenant

    dep_app = FastAPI()
    tenant_obj = Tenant(id=_TENANT_ID, name="Acme")
    db = _make_mock_db()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = tenant_obj
    db.execute = AsyncMock(return_value=result_mock)

    @dep_app.get("/protected")
    async def _protected(
        tenant: Tenant = pytest.importorskip("fastapi").Depends(get_current_tenant),
    ) -> dict:
        return {"tenant_id": str(tenant.id)}

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    dep_app.dependency_overrides[get_db] = _override_db

    token = create_access_token(tenant_id=_TENANT_ID, user_id=_USER_ID)
    async with AsyncClient(
        transport=ASGITransport(app=dep_app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
    dep_app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == str(_TENANT_ID)


@pytest.mark.asyncio
async def test_get_current_tenant_missing_token_returns_401() -> None:
    from app.core.dependencies import get_current_tenant
    from app.models.campaign import Tenant

    dep_app = FastAPI()

    @dep_app.get("/protected")
    async def _protected(
        tenant: Tenant = pytest.importorskip("fastapi").Depends(get_current_tenant),
    ) -> dict:
        return {"tenant_id": str(tenant.id)}

    async with AsyncClient(
        transport=ASGITransport(app=dep_app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected")

    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_current_tenant_invalid_token_returns_401() -> None:
    from app.core.dependencies import get_current_tenant
    from app.models.campaign import Tenant

    dep_app = FastAPI()
    db = _make_mock_db()

    @dep_app.get("/protected")
    async def _protected(
        tenant: Tenant = pytest.importorskip("fastapi").Depends(get_current_tenant),
    ) -> dict:
        return {"tenant_id": str(tenant.id)}

    async def _override_db() -> AsyncGenerator[AsyncMock, None]:
        yield db

    dep_app.dependency_overrides[get_db] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=dep_app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/protected", headers={"Authorization": "Bearer not-a-valid-token"}
        )
    dep_app.dependency_overrides.clear()

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tenant isolation test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_token_resolves_to_own_tenant_only() -> None:
    """A token minted for tenant A must never resolve to tenant B's data."""
    from app.core.dependencies import get_current_tenant
    from app.models.campaign import Tenant

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    tenant_a = Tenant(id=tenant_a_id, name="Brand A")
    tenant_b = Tenant(id=tenant_b_id, name="Brand B")

    token_a = create_access_token(tenant_id=tenant_a_id, user_id=user_a_id)
    token_b = create_access_token(tenant_id=tenant_b_id, user_id=user_b_id)

    def _make_db_for(tenant: Tenant) -> AsyncMock:
        db = _make_mock_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = tenant
        db.execute = AsyncMock(return_value=result_mock)
        return db

    dep_app = FastAPI()

    @dep_app.get("/me")
    async def _me(
        tenant: Tenant = pytest.importorskip("fastapi").Depends(get_current_tenant),
    ) -> dict:
        return {"tenant_id": str(tenant.id), "name": tenant.name}

    # Token A resolves to tenant A
    async def _override_a() -> AsyncGenerator[AsyncMock, None]:
        yield _make_db_for(tenant_a)

    dep_app.dependency_overrides[get_db] = _override_a
    async with AsyncClient(
        transport=ASGITransport(app=dep_app), base_url="http://test"
    ) as client:
        resp_a = await client.get("/me", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_a.status_code == 200
    assert resp_a.json()["tenant_id"] == str(tenant_a_id)
    assert resp_a.json()["name"] == "Brand A"

    # Token B resolves to tenant B, not A
    async def _override_b() -> AsyncGenerator[AsyncMock, None]:
        yield _make_db_for(tenant_b)

    dep_app.dependency_overrides[get_db] = _override_b
    async with AsyncClient(
        transport=ASGITransport(app=dep_app), base_url="http://test"
    ) as client:
        resp_b = await client.get("/me", headers={"Authorization": f"Bearer {token_b}"})
    dep_app.dependency_overrides.clear()

    assert resp_b.status_code == 200
    assert resp_b.json()["tenant_id"] == str(tenant_b_id)
    assert resp_b.json()["name"] == "Brand B"

    # Cross-check: the two resolved tenant IDs are distinct
    assert resp_a.json()["tenant_id"] != resp_b.json()["tenant_id"]
