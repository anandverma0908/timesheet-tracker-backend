"""add pr reviews

Revision ID: 018_add_pr_reviews
Revises: 017_merge_all_heads
Create Date: 2026-05-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "018_add_pr_reviews"
down_revision: Union[str, Sequence[str], None] = "017_merge_all_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pr_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_repo", sa.String(length=500), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("pr_title", sa.String(length=500), nullable=False),
        sa.Column("pr_author", sa.String(length=200), nullable=True),
        sa.Column("pr_url", sa.String(length=1000), nullable=True),
        sa.Column("base_branch", sa.String(length=500), nullable=True),
        sa.Column("head_branch", sa.String(length=500), nullable=True),
        sa.Column("linked_tickets", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("linked_story_key", sa.String(length=50), nullable=True),
        sa.Column("requirement_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("changed_files", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("total_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("critical_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("high_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("medium_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_pr_reviews_org_repo_pr",
        "pr_reviews",
        ["org_id", "github_repo", "pr_number"],
    )
    op.create_index("ix_pr_reviews_repo_created", "pr_reviews", ["github_repo", "created_at"])
    op.create_index("ix_pr_reviews_status", "pr_reviews", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pr_reviews_status", table_name="pr_reviews")
    op.drop_index("ix_pr_reviews_repo_created", table_name="pr_reviews")
    op.drop_constraint("uq_pr_reviews_org_repo_pr", "pr_reviews", type_="unique")
    op.drop_table("pr_reviews")
