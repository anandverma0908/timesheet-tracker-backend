"""add story context to pr reviews

Revision ID: 019_pr_review_story_context
Revises: 018_add_pr_reviews
Create Date: 2026-05-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_pr_review_story_context"
down_revision: Union[str, Sequence[str], None] = "018_add_pr_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE pr_reviews ADD COLUMN IF NOT EXISTS linked_story_key VARCHAR(50)")
    op.execute("ALTER TABLE pr_reviews ADD COLUMN IF NOT EXISTS requirement_context JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.drop_column("pr_reviews", "requirement_context")
    op.drop_column("pr_reviews", "linked_story_key")
