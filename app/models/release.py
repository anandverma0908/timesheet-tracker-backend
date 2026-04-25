from sqlalchemy import Column, String, DateTime, Date, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, gen_uuid, now


class Release(Base):
    __tablename__ = "releases"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod         = Column(String(100), nullable=False)
    name        = Column(String(100), nullable=False)
    description = Column(String, nullable=True)
    status      = Column(String(50), default="unreleased", nullable=False)
    release_date = Column(Date, nullable=True)
    created_at  = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_release_org_pod", "org_id", "pod"),
        Index("ix_release_status", "org_id", "pod", "status"),
    )
