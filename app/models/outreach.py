from pydantic import BaseModel


class OutreachEmailDraft(BaseModel):
    subject_a: str
    subject_b: str
    body: str
    personalization_score: float
    status: str = "pending_approval"
