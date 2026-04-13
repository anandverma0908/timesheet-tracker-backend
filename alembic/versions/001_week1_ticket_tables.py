"""Week 1 — ticket_embeddings, ticket_comments, ticket_attachments, audit_log.
   Also adds is_deleted, description, story_points columns to jira_tickets.

Revision ID: 001_week1
Revises:
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001_week1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enable pgvector extension ─────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Extend jira_tickets ───────────────────────────────────────────────────
    op.add_column("jira_tickets", sa.Column("description",  sa.Text(),    nullable=True))
    op.add_column("jira_tickets", sa.Column("story_points", sa.Integer(), nullable=True))
    op.add_column("jira_tickets", sa.Column("is_deleted",   sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("jira_tickets", sa.Column("sprint_id",    UUID(as_uuid=False), nullable=True))

    op.create_index("ix_jt_is_deleted", "jira_tickets", ["org_id", "is_deleted"])

    # ── ticket_embeddings ─────────────────────────────────────────────────────
    op.create_table(
        "ticket_embeddings",
        sa.Column("id",              UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticket_id",       UUID(as_uuid=False), sa.ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("content_snippet", sa.Text(),    nullable=True),
        sa.Column("updated_at",      sa.DateTime(), server_default=sa.text("NOW()")),
    )
    # The actual vector(384) column must be added via raw SQL — pgvector type
    op.execute("""
        ALTER TABLE ticket_embeddings
        ADD COLUMN embedding vector(384)
    """)
    op.create_index("ix_te_ticket", "ticket_embeddings", ["ticket_id"])

    # ── ticket_comments ───────────────────────────────────────────────────────
    op.create_table(
        "ticket_comments",
        sa.Column("id",         UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticket_id",  UUID(as_uuid=False), sa.ForeignKey("jira_tickets.id",    ondelete="CASCADE"), nullable=False),
        sa.Column("author_id",  UUID(as_uuid=False), sa.ForeignKey("users.id"),           nullable=True),
        sa.Column("body",       sa.Text(),    nullable=False),
        sa.Column("parent_id",  UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_foreign_key(
        "fk_tc_parent", "ticket_comments", "ticket_comments", ["parent_id"], ["id"]
    )
    op.create_index("ix_tc_ticket", "ticket_comments", ["ticket_id"])

    # ── ticket_attachments ────────────────────────────────────────────────────
    op.create_table(
        "ticket_attachments",
        sa.Column("id",          UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticket_id",   UUID(as_uuid=False), sa.ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename",    sa.Text(),    nullable=False),
        sa.Column("filepath",    sa.Text(),    nullable=False),
        sa.Column("size_bytes",  sa.Integer(), nullable=True),
        sa.Column("uploaded_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at",  sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_ta_ticket", "ticket_attachments", ["ticket_id"])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id",          UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id",   UUID(as_uuid=False), nullable=False),
        sa.Column("user_id",     UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("org_id",      UUID(as_uuid=False), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action",      sa.String(100), nullable=False),
        sa.Column("diff_json",   JSONB, nullable=True),
        sa.Column("created_at",  sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_al_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_al_org",    "audit_log", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("ticket_attachments")
    op.drop_table("ticket_comments")
    op.drop_table("ticket_embeddings")

    op.drop_index("ix_jt_is_deleted", table_name="jira_tickets")
    op.drop_column("jira_tickets", "sprint_id")
    op.drop_column("jira_tickets", "is_deleted")
    op.drop_column("jira_tickets", "story_points")
    op.drop_column("jira_tickets", "description")
