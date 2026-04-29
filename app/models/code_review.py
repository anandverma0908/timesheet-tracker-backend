"""
app/models/code_review.py — Persisted snapshots of AI code-review runs.
"""

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, TimestampMixin, gen_uuid, now


class CodeReviewSnapshot(Base, TimestampMixin):
    __tablename__ = "code_review_snapshots"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    label           = Column(String(500), nullable=True)   # human-readable run id from AI engine
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    github_repo     = Column(String(500), nullable=False)
    scanned_files   = Column(JSONB, nullable=True)   # list[str]
    findings        = Column(JSONB, nullable=True)   # list[dict]
    total_count     = Column(Integer, default=0)
    critical_count  = Column(Integer, default=0)
    high_count      = Column(Integer, default=0)
    medium_count    = Column(Integer, default=0)
    run_at          = Column(DateTime, default=now, nullable=False)
