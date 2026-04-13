from sqlalchemy import Column, String, DateTime, Index, Enum as SAEnum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, gen_uuid, now

SYNC_STATUSES = ["running", "success", "failed"]


class AuditLog(Base):
    __tablename__ = "audit_log"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    entity_type = Column(String(100), nullable=False)
    entity_id   = Column(UUID(as_uuid=False), nullable=False)
    user_id     = Column(UUID(as_uuid=False), ForeignKey("users.id"),         nullable=True)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organisations.id",  ondelete="CASCADE"), nullable=False)
    action      = Column(String(100), nullable=False)
    diff_json   = Column(JSONB, nullable=True)
    created_at  = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_al_entity", "entity_type", "entity_id"),
        Index("ix_al_org",    "org_id", "created_at"),
    )


class SyncLog(Base):
    __tablename__ = "sync_log"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    started_at      = Column(DateTime, default=now)
    finished_at     = Column(DateTime, nullable=True)
    status          = Column(SAEnum(*SYNC_STATUSES, name="sync_status"), default="running")
    tickets_synced  = Column(Integer, default=0)
    worklogs_synced = Column(Integer, default=0)
    error           = Column(Text, nullable=True)

    organisation = relationship("Organisation", back_populates="sync_logs",
                                foreign_keys=[org_id],
                                primaryjoin="SyncLog.org_id == Organisation.id")

    __table_args__ = (Index("ix_sl_org_started", "org_id", "started_at"),)
