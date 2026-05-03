"""
app/models/guest.py — Guest access token model for client portal sharing.
"""

from sqlalchemy import Column, String, DateTime, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, gen_uuid, now


class GuestAccessToken(Base):
    __tablename__ = "guest_access_tokens"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id        = Column(UUID(as_uuid=False), nullable=False)
    token         = Column(String(64),  nullable=False, unique=True, index=True)
    email         = Column(String(200), nullable=False)
    name          = Column(String(200), nullable=False)
    allowed_pods  = Column(JSON,        nullable=True)   # list of pod names
    allowed_tickets = Column(JSON,      nullable=True)   # list of ticket keys (optional)
    expires_at    = Column(DateTime,    nullable=True)
    is_active     = Column(Boolean,     default=True, nullable=False)
    created_at    = Column(DateTime,    default=now, nullable=False)
