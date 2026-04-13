from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, Index, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, gen_uuid, now


class WikiSpace(Base):
    __tablename__ = "wiki_spaces"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name         = Column(Text, nullable=False)
    slug         = Column(Text, nullable=False)
    description  = Column(Text, nullable=True)
    access_level = Column(String(50), default="private")
    created_at   = Column(DateTime, default=now)

    pages = relationship("WikiPage", back_populates="space", cascade="all, delete")

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_wiki_space_slug"),
        Index("ix_ws_org", "org_id"),
    )


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    space_id     = Column(UUID(as_uuid=False), ForeignKey("wiki_spaces.id", ondelete="CASCADE"), nullable=False)
    parent_id    = Column(UUID(as_uuid=False), ForeignKey("wiki_pages.id"), nullable=True)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    title        = Column(Text,    nullable=False)
    content_md   = Column(Text,    nullable=True)
    content_html = Column(Text,    nullable=True)
    version      = Column(Integer, default=1)
    author_id    = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    is_deleted   = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=now)
    updated_at   = Column(DateTime, default=now, onupdate=now)

    space     = relationship("WikiSpace",    back_populates="pages")
    children  = relationship("WikiPage",     foreign_keys=[parent_id])
    versions  = relationship("WikiVersion",  back_populates="page",      cascade="all, delete")
    embedding = relationship("WikiEmbedding",back_populates="page",      cascade="all, delete", uselist=False)
    author    = relationship("User",         foreign_keys=[author_id])

    __table_args__ = (
        Index("ix_wp_space",  "space_id"),
        Index("ix_wp_org",    "org_id"),
        Index("ix_wp_parent", "parent_id"),
    )


class WikiVersion(Base):
    __tablename__ = "wiki_versions"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    page_id    = Column(UUID(as_uuid=False), ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False)
    version    = Column(Integer, nullable=False)
    content_md = Column(Text,    nullable=True)
    author_id  = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)

    page   = relationship("WikiPage", back_populates="versions")
    author = relationship("User",     foreign_keys=[author_id])

    __table_args__ = (Index("ix_wv_page", "page_id"),)


class WikiEmbedding(Base):
    __tablename__ = "wiki_embeddings"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    page_id         = Column(UUID(as_uuid=False), ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, unique=True)
    content_snippet = Column(Text,     nullable=True)
    updated_at      = Column(DateTime, default=now, onupdate=now)

    page = relationship("WikiPage", back_populates="embedding")

    __table_args__ = (Index("ix_we_page", "page_id"),)
