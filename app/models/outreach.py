"""Pydantic models for the in-flight copywriter state.

Distinct from the SQLAlchemy OutreachEmail in campaign.py — this represents
an email draft travelling through the CopywriterAgent graph before it is
persisted to the database.
"""

from pydantic import BaseModel


class OutreachEmailDraft(BaseModel):
    subject_a: str
    subject_b: str
    body: str
    personalization_score: float
    status: str = "pending_approval"  # "pending_approval" | "approved" | "rejected"
