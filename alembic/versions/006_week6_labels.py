"""Week 6 — add labels to jira_tickets

Revision ID: 006_week6
Revises: 005_week5
Create Date: 2026-04-15
"""
from alembic import op

revision = '006_week6'
down_revision = '005_week5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jira_tickets ADD COLUMN IF NOT EXISTS labels JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE jira_tickets DROP COLUMN IF EXISTS labels")
