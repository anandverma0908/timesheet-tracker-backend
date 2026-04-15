"""Week 5 — spaces: epics, sprint pod linkage, ticket epic linkage

Revision ID: 005_week5
Revises: 004_week4
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = '005_week5'
down_revision = '004_week4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add pod to sprints
    op.execute("""
        ALTER TABLE sprints
            ADD COLUMN IF NOT EXISTS pod TEXT
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sp_pod ON sprints(pod)")

    # 2. Create epics table
    op.execute("""
        CREATE TABLE IF NOT EXISTS epics (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          UUID REFERENCES organisations(id) ON DELETE CASCADE,
            pod             TEXT NOT NULL,
            title           TEXT NOT NULL,
            color           TEXT,
            start_date      DATE,
            end_date        DATE,
            progress        INTEGER DEFAULT 0,
            task_count      INTEGER DEFAULT 0,
            completed_count INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_epic_org_pod ON epics(org_id, pod)")

    # 3. Add epic_id to jira_tickets
    op.execute("""
        ALTER TABLE jira_tickets
            ADD COLUMN IF NOT EXISTS epic_id UUID REFERENCES epics(id)
    """)

    # 4. Backfill sprint.pod from majority pod among assigned tickets
    op.execute("""
        UPDATE sprints sp
        SET pod = sub.pod
        FROM (
            SELECT
                s.id,
                jt.pod
            FROM sprints s
            JOIN jira_tickets jt ON jt.sprint_id = s.id
            WHERE jt.is_deleted = false
            GROUP BY s.id, jt.pod
            ORDER BY s.id, COUNT(*) DESC
        ) sub
        WHERE sp.id = sub.id
        AND sp.pod IS NULL
    """)

    # 5. Seed epics from existing Epic-type tickets
    op.execute("""
        INSERT INTO epics (org_id, pod, title, color, start_date, end_date, progress, task_count, completed_count)
        SELECT
            jt.org_id,
            COALESCE(jt.pod, jt.project_key, 'Unknown'),
            jt.summary,
            '#4F7EFF',
            jt.jira_created,
            jt.jira_updated,
            0,
            0,
            0
        FROM jira_tickets jt
        WHERE LOWER(jt.issue_type) = 'epic'
          AND jt.is_deleted = false
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE jira_tickets DROP COLUMN IF EXISTS epic_id")
    op.execute("DROP TABLE IF EXISTS epics")
    op.execute("DROP INDEX IF EXISTS ix_sp_pod")
    op.execute("ALTER TABLE sprints DROP COLUMN IF EXISTS pod")
