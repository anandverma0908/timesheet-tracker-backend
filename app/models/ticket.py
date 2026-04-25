from sqlalchemy import (
    Column, String, Float, Integer, Boolean,
    DateTime, Date, Text, Index, UniqueConstraint, ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, gen_uuid, now


class JiraTicket(Base):
    __tablename__ = "jira_tickets"

    id                       = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id                   = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    jira_key                 = Column(String(50),  nullable=False)
    project_key              = Column(String(50),  nullable=False)
    project_name             = Column(String(200), nullable=True)
    summary                  = Column(Text,        nullable=False)
    description              = Column(Text,        nullable=True)
    assignee                 = Column(String(200), nullable=True)
    assignee_email           = Column(String(200), nullable=True)
    reporter                 = Column(String(200), nullable=True)
    status                   = Column(String(100), nullable=True)
    client                   = Column(String(200), nullable=True)
    pod                      = Column(String(100), nullable=True)
    issue_type               = Column(String(100), nullable=True)
    priority                 = Column(String(50),  nullable=True)
    story_points             = Column(Integer,     nullable=True)
    hours_spent              = Column(Float,  default=0)
    original_estimate_hours  = Column(Float,  default=0)
    remaining_estimate_hours = Column(Float,  default=0)
    jira_created             = Column(Date,   nullable=True)
    jira_updated             = Column(Date,   nullable=True)
    url                      = Column(String(500), nullable=True)
    sprint_id                = Column(UUID(as_uuid=False), nullable=True)
    epic_id                  = Column(UUID(as_uuid=False), ForeignKey("epics.id"), nullable=True)
    parent_id                = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id"), nullable=True)
    fix_version              = Column(String(100), nullable=True)
    labels                   = Column(JSONB, nullable=True)
    due_date                 = Column(Date,   nullable=True)
    custom_fields            = Column(JSONB, nullable=True)
    is_deleted               = Column(Boolean, default=False, nullable=False)
    synced_at                = Column(DateTime, default=now, onupdate=now)

    organisation = relationship("Organisation", back_populates="jira_tickets", foreign_keys=[org_id])
    worklogs     = relationship("Worklog",          back_populates="ticket",  cascade="all, delete")
    comments     = relationship("TicketComment",    back_populates="ticket",  cascade="all, delete")
    attachments  = relationship("TicketAttachment", back_populates="ticket",  cascade="all, delete")
    embedding    = relationship("TicketEmbedding",  back_populates="ticket",  cascade="all, delete", uselist=False)

    __table_args__ = (
        UniqueConstraint("org_id", "jira_key", name="uq_org_jira_key"),
        Index("ix_jt_org_updated", "org_id", "jira_updated"),
        Index("ix_jt_assignee",    "org_id", "assignee"),
        Index("ix_jt_pod",         "org_id", "pod"),
        Index("ix_jt_client",      "org_id", "client"),
        Index("ix_jt_project",     "org_id", "project_key"),
        Index("ix_jt_is_deleted",  "org_id", "is_deleted"),
    )


class Worklog(Base):
    __tablename__ = "worklogs"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    ticket_id    = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False)
    author       = Column(String(200), nullable=True)
    author_email = Column(String(200), nullable=True)
    log_date     = Column(Date,  nullable=True)
    hours        = Column(Float, default=0)
    comment      = Column(Text,  nullable=True)

    ticket = relationship("JiraTicket", back_populates="worklogs")

    __table_args__ = (
        Index("ix_wl_ticket", "ticket_id"),
        Index("ix_wl_date",   "log_date"),
        Index("ix_wl_author", "author"),
    )


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    ticket_id  = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False)
    author_id  = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    body       = Column(Text,    nullable=False)
    parent_id  = Column(UUID(as_uuid=False), ForeignKey("ticket_comments.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    ticket  = relationship("JiraTicket",    back_populates="comments")
    author  = relationship("User",          foreign_keys=[author_id])
    replies = relationship("TicketComment", foreign_keys=[parent_id])

    __table_args__ = (Index("ix_tc_ticket", "ticket_id"),)


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    ticket_id   = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False)
    filename    = Column(Text,    nullable=False)
    filepath    = Column(Text,    nullable=False)
    size_bytes  = Column(Integer, nullable=True)
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime, default=now)

    ticket   = relationship("JiraTicket", back_populates="attachments")
    uploader = relationship("User",       foreign_keys=[uploaded_by])

    __table_args__ = (Index("ix_ta_ticket", "ticket_id"),)


class TicketEmbedding(Base):
    __tablename__ = "ticket_embeddings"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    ticket_id       = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False, unique=True)
    content_snippet = Column(Text,     nullable=True)
    updated_at      = Column(DateTime, default=now, onupdate=now)

    ticket = relationship("JiraTicket", back_populates="embedding")

    __table_args__ = (Index("ix_te_ticket", "ticket_id"),)

    # embedding column added back via raw SQL below (pgvector type not in SQLAlchemy by default)


class TicketLink(Base):
    __tablename__ = "ticket_links"

    id               = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id           = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    source_ticket_id = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id", ondelete="CASCADE"), nullable=False)
    target_key       = Column(String(50),  nullable=False)
    target_summary   = Column(Text,        nullable=True)
    link_type        = Column(String(100), nullable=False)
    created_at       = Column(DateTime, default=now)

    source = relationship("JiraTicket", foreign_keys=[source_ticket_id])

    __table_args__ = (
        UniqueConstraint("source_ticket_id", "target_key", "link_type", name="uq_ticket_link"),
        Index("ix_tl_source", "source_ticket_id"),
    )
