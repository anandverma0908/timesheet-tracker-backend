from sqlalchemy import Column, String, Text, Integer, Boolean, Date, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, gen_uuid, now


class Sprint(Base):
    __tablename__ = "sprints"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name       = Column(Text,    nullable=False)
    goal       = Column(Text,    nullable=True)
    start_date = Column(Date,    nullable=True)
    end_date   = Column(Date,    nullable=True)
    status     = Column(String(50), default="planning")  # planning | active | completed
    velocity   = Column(Integer, nullable=True)
    pod        = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_sp_org", "org_id"),
        Index("ix_sp_pod", "pod"),
    )


class Standup(Base):
    __tablename__ = "standups"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id      = Column(UUID(as_uuid=False), ForeignKey("users.id"),                nullable=True)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    date         = Column(Date,    nullable=False)
    yesterday    = Column(Text,    nullable=True)
    today        = Column(Text,    nullable=True)
    blockers     = Column(Text,    nullable=True)
    is_shared    = Column(Boolean, default=False)
    generated_at = Column(DateTime, default=now)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_su_org_date",  "org_id",  "date"),
        Index("ix_su_user_date", "user_id", "date"),
    )


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    topic           = Column(Text,    nullable=False)
    ticket_count    = Column(Integer, default=0)
    wiki_coverage   = Column(Integer, default=0)  # percentage 0–100
    example_tickets = Column(Text,    nullable=True)  # JSON string
    suggestion      = Column(Text,    nullable=True)
    detected_at     = Column(DateTime, default=now)

    __table_args__ = (Index("ix_kg_org", "org_id"),)
