from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, gen_uuid, now


class ChatChannel(Base):
    __tablename__ = "chat_channels"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name       = Column(String(200), nullable=False)
    type       = Column(String(20), nullable=False, default="general")
    pod        = Column(String(100), nullable=True)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now, nullable=False)

    messages    = relationship("ChatMessage", back_populates="channel", cascade="all, delete")
    memberships = relationship("ChatChannelMember", back_populates="channel", cascade="all, delete")

    __table_args__ = (
        Index("ix_chat_channel_org", "org_id"),
        Index("ix_chat_channel_type", "org_id", "type"),
    )


class ChatChannelMember(Base):
    """
    Junction table — which users are in a channel.
    If a channel has zero rows here it is considered public (visible to the whole org).
    Once any member is added, the channel becomes private and only listed for members.
    """
    __tablename__ = "chat_channel_members"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    channel_id = Column(UUID(as_uuid=False), ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    added_by   = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    added_at   = Column(DateTime, default=now, nullable=False)

    channel  = relationship("ChatChannel", back_populates="memberships")
    user     = relationship("User", foreign_keys=[user_id])
    added_by_user = relationship("User", foreign_keys=[added_by])

    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_channel_member"),
        Index("ix_chat_channel_member_channel", "channel_id"),
        Index("ix_chat_channel_member_user", "user_id"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    channel_id = Column(UUID(as_uuid=False), ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    body       = Column(Text, nullable=False)
    parent_id  = Column(UUID(as_uuid=False), ForeignKey("chat_messages.id"), nullable=True)
    created_at = Column(DateTime, default=now, nullable=False)

    channel = relationship("ChatChannel", back_populates="messages")
    author  = relationship("User", foreign_keys=[user_id])
    replies = relationship("ChatMessage", foreign_keys=[parent_id])

    __table_args__ = (
        Index("ix_chat_message_channel", "channel_id", "created_at"),
    )
