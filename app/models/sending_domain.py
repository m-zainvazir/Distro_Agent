import uuid

from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import Base, TenantMixin, TimestampMixin


class SendingDomain(Base, TenantMixin, TimestampMixin):
    __tablename__ = "sending_domains"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    warmup_day = Column(Integer, nullable=False, default=1)
    send_count = Column(Integer, nullable=False, default=0)
    bounce_count = Column(Integer, nullable=False, default=0)
    paused = Column(Boolean, nullable=False, default=False)
    paused_reason = Column(String(255), nullable=True)
    last_send_date = Column(Date, nullable=True)
    emails_sent_today = Column(Integer, nullable=False, default=0)
