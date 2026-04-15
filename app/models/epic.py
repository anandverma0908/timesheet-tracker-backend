from sqlalchemy import Column, String, Text, Integer, Date, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, gen_uuid, now


class Epic(Base):
    __tablename__ = "epics"

    id               = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id           = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod              = Column(String(100), nullable=False)
    title            = Column(Text,    nullable=False)
    color            = Column(String(50), nullable=True)
    start_date       = Column(Date,    nullable=True)
    end_date         = Column(Date,    nullable=True)
    progress         = Column(Integer, default=0)
    task_count       = Column(Integer, default=0)
    completed_count  = Column(Integer, default=0)
    created_at       = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_epic_org_pod", "org_id", "pod"),
    )
