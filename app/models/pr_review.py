"""
app/models/pr_review.py — Persisted EOS pull-request review runs.
"""

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, TimestampMixin, gen_uuid, now


class PRReview(Base, TimestampMixin):
    __tablename__ = "pr_reviews"
    __table_args__ = (
        UniqueConstraint("org_id", "github_repo", "pr_number", name="uq_pr_reviews_org_repo_pr"),
    )

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    github_repo     = Column(String(500), nullable=False)
    pr_number       = Column(Integer, nullable=False)
    pr_title        = Column(String(500), nullable=False)
    pr_author       = Column(String(200), nullable=True)
    pr_url          = Column(String(1000), nullable=True)
    base_branch     = Column(String(500), nullable=True)
    head_branch     = Column(String(500), nullable=True)
    linked_tickets  = Column(JSONB, nullable=False, default=list)
    changed_files   = Column(JSONB, nullable=False, default=list)
    status          = Column(String(50), nullable=False, default="pending")
    findings        = Column(JSONB, nullable=False, default=list)
    total_count     = Column(Integer, default=0)
    critical_count  = Column(Integer, default=0)
    high_count      = Column(Integer, default=0)
    medium_count    = Column(Integer, default=0)
    created_at      = Column(DateTime, default=now, nullable=False)
    analyzed_at     = Column(DateTime, nullable=True)
