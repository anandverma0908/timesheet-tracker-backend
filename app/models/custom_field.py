from sqlalchemy import Column, String, Integer, Boolean, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base, gen_uuid, now


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id        = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod           = Column(String(100), nullable=False)
    name          = Column(String(200), nullable=False)
    field_type    = Column(String(50), nullable=False)   # text | number | select | date | checkbox
    options       = Column(JSONB, nullable=True)         # ["option1", "option2"] for select
    is_required   = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    created_at    = Column(DateTime, default=now)

    __table_args__ = (
        Index("ix_cfd_org_pod", "org_id", "pod"),
    )
