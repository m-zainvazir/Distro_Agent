import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin


class ScoringWeights(Base, TimestampMixin):
    __tablename__ = "scoring_weights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # One row per vertical (e.g. "footwear", "skincare"). "all" = global fallback.
    vertical_tag = Column(String(100), nullable=False, unique=True, index=True)
    visual_weight = Column(Float, nullable=False, default=0.35)
    category_weight = Column(Float, nullable=False, default=0.25)
    price_weight = Column(Float, nullable=False, default=0.20)
    engagement_weight = Column(Float, nullable=False, default=0.10)
    wholesale_weight = Column(Float, nullable=False, default=0.10)
    # Null until first calibration run; updated each time weights change.
    calibrated_at = Column(DateTime, nullable=True)
    # Decided outcomes (wins + losses) used in the last calibration.
    sample_size = Column(Integer, nullable=False, default=0)
