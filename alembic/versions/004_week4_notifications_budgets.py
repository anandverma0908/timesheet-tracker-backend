"""Week 4 — notifications, client_budgets, burn_rate_alerts

Revision ID: 004_week4
Revises: 003_week3
Create Date: 2026-04-12
"""
from alembic import op

revision = '004_week4'
down_revision = '003_week3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID REFERENCES users(id),
            org_id     UUID REFERENCES organisations(id) ON DELETE CASCADE,
            type       TEXT NOT NULL,
            title      TEXT NOT NULL,
            body       TEXT,
            link       TEXT,
            is_read    BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_notif_user_read ON notifications(user_id, is_read)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notif_org ON notifications(org_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS client_budgets (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id       UUID REFERENCES organisations(id) ON DELETE CASCADE,
            client       TEXT NOT NULL,
            month        INTEGER NOT NULL,
            year         INTEGER NOT NULL,
            budget_hours NUMERIC NOT NULL,
            created_at   TIMESTAMP DEFAULT NOW(),
            UNIQUE(org_id, client, month, year)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS burn_rate_alerts (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        UUID REFERENCES organisations(id) ON DELETE CASCADE,
            client        TEXT NOT NULL,
            threshold_pct INTEGER NOT NULL,
            hours_used    NUMERIC,
            hours_budget  NUMERIC,
            nova_summary  TEXT,
            notified_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bra_org ON burn_rate_alerts(org_id, notified_at)")

    # pgvector IVFFlat index for fast ANN search (requires at least 1 row)
    op.execute("""
        DO $$
        BEGIN
            IF (SELECT COUNT(*) FROM ticket_embeddings) > 0 THEN
                CREATE INDEX IF NOT EXISTS ix_te_ivfflat
                ON ticket_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            END IF;
        END$$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF (SELECT COUNT(*) FROM wiki_embeddings WHERE embedding IS NOT NULL) > 0 THEN
                CREATE INDEX IF NOT EXISTS ix_we_ivfflat
                ON wiki_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 50);
            END IF;
        END$$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_we_ivfflat")
    op.execute("DROP INDEX IF EXISTS ix_te_ivfflat")
    op.execute("DROP TABLE IF EXISTS burn_rate_alerts")
    op.execute("DROP TABLE IF EXISTS client_budgets")
    op.execute("DROP TABLE IF EXISTS notifications")
