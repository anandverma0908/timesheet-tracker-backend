"""Add duplicate_similarity_log table for threshold calibration

Revision ID: 013_duplicate_similarity_log
Revises: 2b52b27118ec
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = "013_duplicate_similarity_log"
down_revision = "2b52b27118ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duplicate_similarity_log",
        sa.Column("id",           sa.String(36), primary_key=True),
        sa.Column("org_id",       sa.String(36), nullable=False, index=True),
        sa.Column("query_snippet", sa.Text,       nullable=True),
        sa.Column("jira_key",     sa.String(50),  nullable=True),
        sa.Column("similarity",   sa.Float,        nullable=False),
        sa.Column("created_at",   sa.DateTime,     nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_dsl_org_created", "duplicate_similarity_log", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_table("duplicate_similarity_log")
