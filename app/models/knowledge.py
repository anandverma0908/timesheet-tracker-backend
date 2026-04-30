"""
app/models/knowledge.py — Decision (ADR) and Process (SOP/Runbook) ORM models.
"""

from sqlalchemy import Column, String, Boolean, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"

    id              = Column(String(36), primary_key=True, default=gen_uuid)
    org_id          = Column(String(36), nullable=False, index=True)
    number          = Column(Integer, nullable=False)
    title           = Column(String(500), nullable=False)
    status          = Column(String(50), nullable=False, default="proposed")
    owner           = Column(String(200))
    date            = Column(String(20))
    context         = Column(Text)
    decision        = Column(Text)
    rationale       = Column(Text)
    alternatives    = Column(ARRAY(Text), default=list)
    consequences    = Column(Text)
    linked_tickets  = Column(ARRAY(Text), default=list)
    tags            = Column(ARRAY(Text), default=list)
    space_id        = Column(String(36), nullable=True)
    org_level       = Column(Boolean, default=False)
    is_deleted      = Column(Boolean, default=False)


class ProcessStep(JSONB):
    """Stored inline as JSONB — not a separate table."""
    pass


class Process(Base, TimestampMixin):
    __tablename__ = "processes"

    id                  = Column(String(36), primary_key=True, default=gen_uuid)
    org_id              = Column(String(36), nullable=False, index=True)
    title               = Column(String(500), nullable=False)
    category            = Column(String(100), nullable=False, default="workflow")
    status              = Column(String(50), nullable=False, default="active")
    owner               = Column(String(200))
    last_updated        = Column(String(20))
    description         = Column(Text)
    steps               = Column(JSONB, default=list)
    tags                = Column(ARRAY(Text), default=list)
    compliance_required = Column(Boolean, default=False)
    avg_completion_time = Column(String(50))
    run_count           = Column(Integer, default=0)
    space_id            = Column(String(36), nullable=True)
    org_level           = Column(Boolean, default=False)
    is_deleted          = Column(Boolean, default=False)
