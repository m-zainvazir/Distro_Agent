import uuid

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    whatsapp_number = Column(String(20), nullable=True)
    plan = Column(String(50), nullable=False, default="free")

    users = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    brand_profiles = relationship(
        "BrandProfileRecord", back_populates="tenant", cascade="all, delete-orphan"
    )
    store_candidates = relationship(
        "StoreCandidate", back_populates="tenant", cascade="all, delete-orphan"
    )
    outreach_campaigns = relationship(
        "OutreachCampaign", back_populates="tenant", cascade="all, delete-orphan"
    )


class BrandProfileRecord(Base, TenantMixin, TimestampMixin):
    """Persisted brand intelligence result. Named BrandProfileRecord to avoid
    collision with the Pydantic BrandProfile in app/models/brand_profile.py."""

    __tablename__ = "brand_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Override mixin to add FK
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_url = Column(String(500), nullable=False)
    brand_name = Column(String(255), nullable=False)
    aesthetic_keywords = Column(JSONB, nullable=True)   # list[str]
    price_range_min = Column(Float, nullable=True)
    price_range_max = Column(Float, nullable=True)
    embedding_vector = Column(JSONB, nullable=True)     # list[float]

    tenant = relationship("Tenant", back_populates="brand_profiles")
    outreach_campaigns = relationship(
        "OutreachCampaign", back_populates="brand_profile", cascade="all, delete-orphan"
    )


class StoreCandidate(Base, TenantMixin, TimestampMixin):
    __tablename__ = "store_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    google_place_id = Column(String(255), nullable=True, index=True)
    instagram_handle = Column(String(100), nullable=True)
    vibe_score = Column(Float, nullable=True)
    lead_score = Column(Float, nullable=True)
    # Values: "new" | "contacted" | "replied" | "qualified" | "rejected"
    status = Column(String(50), nullable=False, default="new")

    tenant = relationship("Tenant", back_populates="store_candidates")
    outreach_emails = relationship(
        "OutreachEmail", back_populates="store", cascade="all, delete-orphan"
    )


class OutreachCampaign(Base, TenantMixin, TimestampMixin):
    __tablename__ = "outreach_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("brand_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Values: "draft" | "active" | "paused" | "completed"
    status = Column(String(50), nullable=False, default="draft")

    tenant = relationship("Tenant", back_populates="outreach_campaigns")
    brand_profile = relationship("BrandProfileRecord", back_populates="outreach_campaigns")
    outreach_emails = relationship(
        "OutreachEmail", back_populates="campaign", cascade="all, delete-orphan"
    )


class OutreachEmail(Base, TimestampMixin):
    __tablename__ = "outreach_emails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("outreach_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("store_candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id = Column(String(255), nullable=True, index=True)  # LangGraph checkpoint thread
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    to_email = Column(String(255), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    message_id = Column(String(255), nullable=True)
    reply_received = Column(Boolean, nullable=False, default=False)
    reply_content = Column(Text, nullable=True)
    reply_intent = Column(String(50), nullable=True)
    gmail_thread_id = Column(String(255), nullable=True)
    follow_up_count = Column(Integer, nullable=False, default=0)
    # Values: "pending" | "pending_approval" | "approved" | "sent" | "bounced" | "replied" | "converted" | "ignored"
    outcome = Column(String(50), nullable=False, default="pending")

    campaign = relationship("OutreachCampaign", back_populates="outreach_emails")
    store = relationship("StoreCandidate", back_populates="outreach_emails")
