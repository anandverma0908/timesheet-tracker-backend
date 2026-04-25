from sqlalchemy import Column, String, DateTime, Boolean, Integer, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, gen_uuid, now


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id               = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id           = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod              = Column(String(100), nullable=False)
    name             = Column(String(200), nullable=False)
    is_active        = Column(Boolean, default=True, nullable=False)
    trigger_type     = Column(String(100), nullable=False)
    trigger_config   = Column(JSONB, nullable=False, default=dict)
    condition_type   = Column(String(100), nullable=True)
    condition_config = Column(JSONB, nullable=True)
    action_type      = Column(String(100), nullable=False)
    action_config    = Column(JSONB, nullable=False, default=dict)
    created_by       = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at       = Column(DateTime, default=now)
    run_count        = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_ar_org_pod_active", "org_id", "pod", "is_active"),
        Index("ix_ar_trigger", "trigger_type", "is_active"),
    )
