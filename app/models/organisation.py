from sqlalchemy import Column, String, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, gen_uuid


class Organisation(Base, TimestampMixin):
    __tablename__ = "organisations"

    id                = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name              = Column(String(200), nullable=False)
    jira_url          = Column(String(500), nullable=False)
    jira_email        = Column(String(200), nullable=False)
    jira_api_token    = Column(Text, nullable=False)
    jira_project_key  = Column(String(50),  nullable=True)
    jira_client_field = Column(String(50),  default="customfield_10233")
    jira_pod_field    = Column(String(50),  default="customfield_10193")

    users          = relationship("User",        back_populates="organisation", cascade="all, delete")
    jira_tickets   = relationship("JiraTicket",  back_populates="organisation", cascade="all, delete")
    manual_entries = relationship("ManualEntry", back_populates="organisation", cascade="all, delete")
    sync_logs      = relationship("SyncLog",     back_populates="organisation", cascade="all, delete")
