from sqlalchemy import Column, String, Text, DateTime, Boolean, UniqueConstraint, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, gen_uuid

USER_ROLES    = ["admin", "engineering_manager", "tech_lead", "team_member", "finance_viewer"]
USER_STATUSES = ["pending", "active", "inactive"]


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id        = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name          = Column(String(200), nullable=False)
    email         = Column(String(200), nullable=False)
    role          = Column(SAEnum(*USER_ROLES,    name="user_role"),   nullable=False, default="team_member")
    pod           = Column(String(100), nullable=True)
    pods          = Column(Text,        nullable=True)
    emp_no        = Column(String(50),  nullable=True)
    title         = Column(String(200), nullable=True)
    reporting_to  = Column(String(50),  nullable=True)
    status        = Column(SAEnum(*USER_STATUSES, name="user_status"), nullable=False, default="pending")
    invited_by    = Column(UUID(as_uuid=False), nullable=True)
    password_hash = Column(Text, nullable=True)
    last_login    = Column(DateTime, nullable=True)

    organisation   = relationship("Organisation", back_populates="users", foreign_keys=[org_id])
    manual_entries = relationship("ManualEntry",  back_populates="user",           cascade="all, delete")

    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_org_email"),)
