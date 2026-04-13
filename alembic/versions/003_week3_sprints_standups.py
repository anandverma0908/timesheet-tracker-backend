"""Week 3 — sprints + standups tables

Revision ID: 003_week3
Revises: 002_week2
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa

revision = '003_week3'
down_revision = '002_week2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sprints (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id      UUID REFERENCES organisations(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            goal        TEXT,
            start_date  DATE,
            end_date    DATE,
            status      TEXT DEFAULT 'planning',
            velocity    INTEGER,
            created_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sp_org ON sprints(org_id)")

    # sprint_id already exists on jira_tickets from W1 migration; add story_points if missing
    op.execute("""
        ALTER TABLE jira_tickets
            ADD COLUMN IF NOT EXISTS story_points INTEGER
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS standups (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID REFERENCES users(id),
            org_id       UUID REFERENCES organisations(id) ON DELETE CASCADE,
            date         DATE NOT NULL,
            yesterday    TEXT,
            today        TEXT,
            blockers     TEXT,
            is_shared    BOOLEAN DEFAULT false,
            generated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, date)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_su_org_date ON standups(org_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_su_user_date ON standups(user_id, date)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_gaps (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          UUID REFERENCES organisations(id) ON DELETE CASCADE,
            topic           TEXT NOT NULL,
            ticket_count    INTEGER DEFAULT 0,
            wiki_coverage   FLOAT  DEFAULT 0,
            example_tickets JSONB,
            suggestion      TEXT,
            detected_at     TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_kg_org ON knowledge_gaps(org_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_gaps")
    op.execute("DROP TABLE IF EXISTS standups")
    op.execute("DROP TABLE IF EXISTS sprints")
