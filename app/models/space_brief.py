"""Cached AI-generated space briefs to ensure deterministic output on refresh."""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from app.models.base import gen_uuid, now


class SpaceBrief(Base):
    __tablename__ = "space_briefs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id = Column(
        UUID(as_uuid=False),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pod = Column(String(100), nullable=False, index=True)

    brief = Column(Text)
    velocity_signal = Column(Text)
    risk_signal = Column(Text)
    recommendation = Column(Text)

    # Hash of the input data used to generate this brief.
    # If the data changes, the hash changes and we regenerate.
    data_hash = Column(String(64), nullable=False)

    created_at = Column(DateTime, default=now, nullable=False)
    updated_at = Column(DateTime, default=now, onupdate=now, nullable=False)

    __table_args__ = (
        # One cached brief per pod per org
        {"sqlite_autoincrement": True},
    )
