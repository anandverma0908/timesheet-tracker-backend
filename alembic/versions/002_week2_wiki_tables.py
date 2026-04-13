"""Week 2 — wiki_spaces, wiki_pages, wiki_versions, wiki_embeddings.

Revision ID: 002_week2
Revises: 001_week1
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002_week2"
down_revision = "001_week1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── wiki_spaces ───────────────────────────────────────────────────────────
    op.create_table(
        "wiki_spaces",
        sa.Column("id",           UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id",       UUID(as_uuid=False), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",         sa.Text(), nullable=False),
        sa.Column("slug",         sa.Text(), nullable=False),
        sa.Column("description",  sa.Text(), nullable=True),
        sa.Column("access_level", sa.String(50), server_default="private"),
        sa.Column("created_at",   sa.DateTime(), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("org_id", "slug", name="uq_wiki_space_slug"),
    )
    op.create_index("ix_ws_org", "wiki_spaces", ["org_id"])

    # ── wiki_pages ────────────────────────────────────────────────────────────
    op.create_table(
        "wiki_pages",
        sa.Column("id",           UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("space_id",     UUID(as_uuid=False), sa.ForeignKey("wiki_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id",    UUID(as_uuid=False), nullable=True),
        sa.Column("org_id",       UUID(as_uuid=False), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title",        sa.Text(),    nullable=False),
        sa.Column("content_md",   sa.Text(),    nullable=True),
        sa.Column("content_html", sa.Text(),    nullable=True),
        sa.Column("version",      sa.Integer(), server_default="1"),
        sa.Column("author_id",    UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_deleted",   sa.Boolean(), server_default="false"),
        sa.Column("created_at",   sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at",   sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_foreign_key(
        "fk_wp_parent", "wiki_pages", "wiki_pages", ["parent_id"], ["id"]
    )
    op.create_index("ix_wp_space",  "wiki_pages", ["space_id"])
    op.create_index("ix_wp_org",    "wiki_pages", ["org_id"])
    op.create_index("ix_wp_parent", "wiki_pages", ["parent_id"])

    # ── wiki_versions ─────────────────────────────────────────────────────────
    op.create_table(
        "wiki_versions",
        sa.Column("id",         UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("page_id",    UUID(as_uuid=False), sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version",    sa.Integer(), nullable=False),
        sa.Column("content_md", sa.Text(),    nullable=True),
        sa.Column("author_id",  UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_wv_page", "wiki_versions", ["page_id"])

    # ── wiki_embeddings ───────────────────────────────────────────────────────
    op.create_table(
        "wiki_embeddings",
        sa.Column("id",              UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("page_id",         UUID(as_uuid=False), sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("content_snippet", sa.Text(),    nullable=True),
        sa.Column("updated_at",      sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.execute("ALTER TABLE wiki_embeddings ADD COLUMN embedding vector(384)")
    op.create_index("ix_we_page", "wiki_embeddings", ["page_id"])


def downgrade() -> None:
    op.drop_table("wiki_embeddings")
    op.drop_table("wiki_versions")
    op.drop_table("wiki_pages")
    op.drop_table("wiki_spaces")
