from sqlalchemy import Column, String, DateTime, Boolean, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, gen_uuid, now


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name       = Column(String(200), nullable=False)
    filters    = Column(JSONB, nullable=False, default=dict)
    is_shared  = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_sf_org_user", "org_id", "user_id"),
        Index("ix_sf_org_shared", "org_id", "is_shared"),
    )
