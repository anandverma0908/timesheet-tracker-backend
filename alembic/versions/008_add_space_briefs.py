"""Add space_briefs table for cached AI-generated pod briefs.

Revision ID: 008_add_space_briefs
Revises: 007_add_goals
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008_add_space_briefs"
down_revision = "007_add_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("pod", sa.String(length=100), nullable=False),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("velocity_signal", sa.Text(), nullable=True),
        sa.Column("risk_signal", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_space_brief_org", "space_briefs", ["org_id"])
    op.create_index("ix_space_brief_pod", "space_briefs", ["pod"])
    op.create_index("ix_space_brief_org_pod", "space_briefs", ["org_id", "pod"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_space_brief_org_pod", table_name="space_briefs")
    op.drop_index("ix_space_brief_pod", table_name="space_briefs")
    op.drop_index("ix_space_brief_org", table_name="space_briefs")
    op.drop_table("space_briefs")
