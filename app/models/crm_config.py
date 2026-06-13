"""TenantCrmConfig — per-tenant CRM integration settings."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class TenantCrmConfig(Base, TimestampMixin):
    """One row per tenant; stores which CRM to push events to and how to auth.

    crm_type:
        "webhook"       — POST to webhook_url with HMAC-signed payload (n8n/Zapier/Make)
        "hubspot"       — HubSpot CRM v3 API, api_key = Private App token
        "salesforce"    — Salesforce REST API, api_key = OAuth access token,
                          extra_config["instance_url"] = Salesforce instance URL
        "google_sheets" — Google Sheets API v4, spreadsheet_id + sheet_name required,
                          extra_config stores OAuth tokens for the service account
    """

    __tablename__ = "tenant_crm_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one CRM config per tenant
        index=True,
    )
    crm_type = Column(String(50), nullable=False)

    # Webhook / n8n / Zapier endpoint (also used as base for all adapter types)
    webhook_url = Column(String(2000), nullable=True)

    # Auth credentials — stored plain; encrypt at rest in production via Vault / KMS
    api_key = Column(Text, nullable=True)

    # Google Sheets specific
    spreadsheet_id = Column(String(255), nullable=True)
    sheet_name = Column(String(255), nullable=True, default="DistroAgent")

    # Signs outgoing webhook POSTs so tenants can verify authenticity
    hmac_secret = Column(String(255), nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)

    # CRM-specific extras (Salesforce instance_url, Google OAuth tokens, etc.)
    extra_config = Column(JSONB, nullable=True)

    tenant = relationship("Tenant")
