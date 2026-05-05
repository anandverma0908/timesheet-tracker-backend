"""add is_private to chat_channels

Revision ID: 016_chat_is_private_column
Revises: 015_fix_chat_channels_columns
Create Date: 2026-05-05

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "016_chat_is_private_column"
down_revision: Union[str, Sequence[str], None] = "015_fix_chat_channels_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[0] for row in conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='chat_channels'")
    )]
    if "is_private" not in existing:
        op.add_column("chat_channels",
            sa.Column("is_private", sa.Boolean, nullable=False, server_default="false")
        )


def downgrade() -> None:
    op.drop_column("chat_channels", "is_private")
