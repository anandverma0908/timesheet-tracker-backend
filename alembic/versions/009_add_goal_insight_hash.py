"""Add nova_insight_hash to goals table.

Revision ID: 009_add_goal_insight_hash
Revises: 008_add_space_briefs
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "009_add_goal_insight_hash"
down_revision = "008_add_space_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("goals", sa.Column("nova_insight_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("goals", "nova_insight_hash")
