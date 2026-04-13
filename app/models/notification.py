from sqlalchemy import Column, String, Text, Boolean, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, gen_uuid, now


class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id    = Column(UUID(as_uuid=False), ForeignKey("users.id"),                nullable=True)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    type       = Column(String(100), nullable=False)   # ticket_assigned | mentioned | sprint_started | standup_ready | burn_rate_alert
    title      = Column(Text,        nullable=False)
    body       = Column(Text,        nullable=True)
    link       = Column(Text,        nullable=True)
    is_read    = Column(Boolean,     default=False)
    created_at = Column(DateTime,    default=now)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_notif_user_read", "user_id", "is_read"),
        Index("ix_notif_org",       "org_id",  "created_at"),
    )
