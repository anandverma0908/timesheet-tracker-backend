from sqlalchemy import Column, String, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, gen_uuid


class SpaceMember(Base, TimestampMixin):
    __tablename__ = "space_members"

    id      = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id  = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod     = Column(String(100), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role    = Column(String(50), nullable=False, default="member")  # "lead" | "member"

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("org_id", "pod", "user_id", name="uq_space_member"),
    )
