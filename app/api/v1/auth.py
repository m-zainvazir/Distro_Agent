import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import logger
from app.core.security import create_access_token, hash_password, verify_password
from app.models.campaign import Tenant
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(
    body: SignupRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered.")

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name=body.brand_name)
    user = User(
        id=user_id,
        email=body.email,
        hashed_password=hash_password(body.password),
        tenant_id=tenant_id,
    )
    db.add(tenant)
    db.add(user)
    await db.commit()
    logger.info("signup_success", email=body.email, tenant_id=str(tenant_id))

    token = create_access_token(tenant_id=tenant_id, user_id=user_id)
    return TokenResponse(access_token=token, tenant_id=tenant_id)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, cast(str, user.hashed_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    logger.info("login_success", email=body.email)
    tenant_id = cast(uuid.UUID, user.tenant_id)
    user_id = cast(uuid.UUID, user.id)
    token = create_access_token(tenant_id=tenant_id, user_id=user_id)
    return TokenResponse(access_token=token, tenant_id=tenant_id)
