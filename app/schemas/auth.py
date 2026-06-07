import uuid

from pydantic import BaseModel


class SignupRequest(BaseModel):
    email: str
    password: str
    brand_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID
