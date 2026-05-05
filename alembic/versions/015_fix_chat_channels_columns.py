"""fix chat_channels missing columns

Revision ID: 015_fix_chat_channels_columns
Revises: 014_add_chat_tables
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "015_fix_chat_channels_columns"
down_revision: Union[str, Sequence[str], None] = "014_add_chat_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # chat_channels — add missing columns if they don't exist
    existing = [row[0] for row in conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='chat_channels'")
    )]

    if "created_by" not in existing:
        op.add_column("chat_channels",
            sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True)
        )

    if "pod" not in existing:
        op.add_column("chat_channels",
            sa.Column("pod", sa.String(100), nullable=True)
        )

    # chat_channel_members — add missing columns if they don't exist
    existing_m = [row[0] for row in conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='chat_channel_members'")
    )]

    if "added_by" not in existing_m:
        op.add_column("chat_channel_members",
            sa.Column("added_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True)
        )

    if "added_at" not in existing_m:
        op.add_column("chat_channel_members",
            sa.Column("added_at", sa.DateTime, nullable=False, server_default=sa.func.now())
        )


def downgrade() -> None:
    pass
