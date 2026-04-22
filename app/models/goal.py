from sqlalchemy import Column, String, Text, Integer, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, gen_uuid, now


class Goal(Base):
    __tablename__ = "goals"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    quarter = Column(String(20), nullable=False, default="Q2 2025")
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    owner = Column(String(200), nullable=True)
    status = Column(String(50), default="on_track")  # on_track | at_risk | behind | complete
    overall_progress = Column(Integer, default=0)
    key_results = Column(JSONB, default=list)  # [{id, title, current, target, unit, linked_tickets, status}]
    linked_sprints = Column(JSONB, default=list)  # ["Sprint 8", "Sprint 9"]
    nova_insight = Column(Text, nullable=True)
    nova_insight_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    __table_args__ = (
        Index("ix_goal_org", "org_id"),
        Index("ix_goal_quarter", "org_id", "quarter"),
    )
