"""Add goals table for OKR tracking.

Revision ID: 007_add_goals
Revises: 006_week6_labels
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "007_add_goals"
down_revision = "006_week6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=False), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quarter", sa.String(20), nullable=False, server_default="Q2 2025"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(200), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="on_track"),
        sa.Column("overall_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("key_results", JSONB(), nullable=False, server_default="[]"),
        sa.Column("linked_sprints", JSONB(), nullable=False, server_default="[]"),
        sa.Column("nova_insight", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_goal_org", "goals", ["org_id"])
    op.create_index("ix_goal_quarter", "goals", ["org_id", "quarter"])


def downgrade() -> None:
    op.drop_index("ix_goal_quarter", table_name="goals")
    op.drop_index("ix_goal_org", table_name="goals")
    op.drop_table("goals")
