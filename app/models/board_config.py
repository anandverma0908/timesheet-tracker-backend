from sqlalchemy import Column, String, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, gen_uuid, now


class BoardConfig(Base):
    __tablename__ = "board_configs"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod         = Column(String(100), nullable=False)
    columns     = Column(JSONB, nullable=False, default=list)
    swimlane_by = Column(String(50), nullable=True)
    wip_limits  = Column(JSONB, nullable=False, default=dict)
    created_at  = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_bc_org_pod", "org_id", "pod", unique=True),
    )
