"""
app/models/integration.py — External integration webhooks (Slack, Teams, generic).
"""

from sqlalchemy import Column, String, Boolean, DateTime, Index, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from app.models.base import Base, gen_uuid, now


class Integration(Base):
    __tablename__ = "integrations"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(200), nullable=False)
    type        = Column(String(50),  nullable=False)   # slack | teams | generic_webhook
    webhook_url = Column(Text,        nullable=False)
    events      = Column(ARRAY(Text), nullable=False, default=list)   # ticket_created | status_changed | sprint_started | mention | comment_added
    is_active   = Column(Boolean,     default=True,  nullable=False)
    created_by  = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime,    default=now)
    updated_at  = Column(DateTime,    default=now, onupdate=now)

    __table_args__ = (
        Index("ix_integrations_org_active", "org_id", "is_active"),
        Index("ix_integrations_type", "org_id", "type"),
    )
