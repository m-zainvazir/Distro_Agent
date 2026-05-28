# app/models/base.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class TenantMixin:
    """EVERY table that stores client data MUST inherit this"""
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)