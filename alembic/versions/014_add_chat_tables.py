"""add chat tables

Revision ID: 014_add_chat_tables
Revises: 013_duplicate_similarity_log
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "014_add_chat_tables"
down_revision: Union[str, Sequence[str], None] = "013_duplicate_similarity_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_channels",
        sa.Column("id",         UUID(as_uuid=False), primary_key=True),
        sa.Column("org_id",     UUID(as_uuid=False), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",       sa.String(200),  nullable=False),
        sa.Column("type",       sa.String(20),   nullable=False, server_default="general"),
        sa.Column("pod",        sa.String(100),  nullable=True),
        sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime,     nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_channel_org",  "chat_channels", ["org_id"])
    op.create_index("ix_chat_channel_type", "chat_channels", ["org_id", "type"])

    op.create_table(
        "chat_channel_members",
        sa.Column("id",         UUID(as_uuid=False), primary_key=True),
        sa.Column("channel_id", UUID(as_uuid=False), sa.ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id",    UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_by",   UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at",   sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "user_id", name="uq_channel_member"),
    )
    op.create_index("ix_chat_channel_member_channel", "chat_channel_members", ["channel_id"])
    op.create_index("ix_chat_channel_member_user",    "chat_channel_members", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id",         UUID(as_uuid=False), primary_key=True),
        sa.Column("channel_id", UUID(as_uuid=False), sa.ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id",    UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body",       sa.Text, nullable=False),
        sa.Column("parent_id",  UUID(as_uuid=False), sa.ForeignKey("chat_messages.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_message_channel", "chat_messages", ["channel_id", "created_at"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_channel_members")
    op.drop_table("chat_channels")
