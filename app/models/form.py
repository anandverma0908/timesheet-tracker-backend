"""
app/models/form.py — Form templates and submissions.
"""

from sqlalchemy import Column, String, Text, Boolean, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, gen_uuid, now


class FormTemplate(Base):
    __tablename__ = "form_templates"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    fields_json = Column(JSONB, nullable=False, default=list)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=now, nullable=False)

    __table_args__ = (
        Index("ix_form_tpl_org", "org_id"),
        Index("ix_form_tpl_active", "org_id", "is_active"),
    )


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    form_id         = Column(UUID(as_uuid=False), ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False)
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    submitter_email = Column(String(200), nullable=False)
    responses_json  = Column(JSONB, nullable=False, default=dict)
    status          = Column(String(20), default="new", nullable=False)
    ticket_id       = Column(String(100), nullable=True)
    created_at      = Column(DateTime, default=now, nullable=False)

    __table_args__ = (
        Index("ix_form_sub_form", "form_id"),
        Index("ix_form_sub_org", "org_id"),
        Index("ix_form_sub_status", "org_id", "status"),
    )
