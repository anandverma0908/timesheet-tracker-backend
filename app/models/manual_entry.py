from sqlalchemy import Column, String, Float, Boolean, Date, Text, Index, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, gen_uuid

ENTRY_TYPES    = ["Meeting", "Bugs", "Feature", "Program Management"]
ENTRY_STATUSES = ["draft", "confirmed", "approved"]


class ManualEntry(Base, TimestampMixin):
    __tablename__ = "manual_entries"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id      = Column(UUID(as_uuid=False), ForeignKey("users.id",         ondelete="CASCADE"), nullable=False)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    entry_date   = Column(Date,        nullable=False)
    activity     = Column(String(500), nullable=False)
    hours        = Column(Float,       nullable=False)
    pod          = Column(String(100), nullable=True)
    client       = Column(String(200), nullable=True)
    entry_type   = Column(SAEnum(*ENTRY_TYPES,    name="entry_type"),   default="Meeting")
    notes        = Column(Text, nullable=True)
    ai_raw_input = Column(Text, nullable=True)
    ai_parsed    = Column(Boolean, default=True)
    status       = Column(SAEnum(*ENTRY_STATUSES, name="entry_status"), default="confirmed")

    user         = relationship("User",         back_populates="manual_entries")
    organisation = relationship("Organisation", back_populates="manual_entries",
                                foreign_keys=[org_id],
                                primaryjoin="ManualEntry.org_id == Organisation.id")

    __table_args__ = (
        Index("ix_me_user_date", "user_id", "entry_date"),
        Index("ix_me_org_date",  "org_id",  "entry_date"),
        Index("ix_me_pod",       "org_id",  "pod"),
        Index("ix_me_client",    "org_id",  "client"),
    )
