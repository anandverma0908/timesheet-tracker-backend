"""
database.py — PostgreSQL connection and all 6 table definitions.
"""

import os, uuid
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Float, Integer,
    Boolean, DateTime, Date, Text, ForeignKey,
    Enum as SAEnum, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/eap_db")

engine = create_engine(
    DATABASE_URL,
    pool_size=10, max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def gen_uuid():  return str(uuid.uuid4())
def now():       return datetime.utcnow()

def get_db():
    db = SessionLocal()
    try:    yield db
    finally: db.close()


# ── organisations ──────────────────────────────────────────────────────────────
class Organisation(Base):
    __tablename__ = "organisations"

    id                = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name              = Column(String(200), nullable=False)
    jira_url          = Column(String(500), nullable=False)
    jira_email        = Column(String(200), nullable=False)
    jira_api_token    = Column(Text,        nullable=False)
    jira_project_key  = Column(String(50),  nullable=True)
    jira_client_field = Column(String(50),  default="customfield_10233")
    jira_pod_field    = Column(String(50),  default="customfield_10193")
    created_at        = Column(DateTime, default=now)
    updated_at        = Column(DateTime, default=now, onupdate=now)

    users          = relationship("User",         back_populates="organisation", cascade="all, delete")
    jira_tickets   = relationship("JiraTicket",   back_populates="organisation", cascade="all, delete")
    manual_entries = relationship("ManualEntry",  back_populates="organisation", cascade="all, delete")
    sync_logs      = relationship("SyncLog",      back_populates="organisation", cascade="all, delete")


# ── users ──────────────────────────────────────────────────────────────────────
USER_ROLES    = ["admin","engineering_manager","tech_lead","team_member","finance_viewer"]
USER_STATUSES = ["pending","active","inactive"]

class User(Base):
    __tablename__ = "users"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id     = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    name       = Column(String(200), nullable=False)
    email      = Column(String(200), nullable=False)
    role       = Column(SAEnum(*USER_ROLES,    name="user_role"),   nullable=False, default="team_member")
    pod          = Column(String(100),  nullable=True)   # comma-separated pod keys e.g. "DPAI,EDM"
    pods         = Column(Text,         nullable=True)   # alias — same as pod, comma-separated
    emp_no       = Column(String(50),   nullable=True)   # Keka employee number e.g. "3SC1463"
    title        = Column(String(200),  nullable=True)   # job title e.g. "SDE3"
    reporting_to = Column(String(50),   nullable=True)   # emp_no of manager
    status       = Column(SAEnum(*USER_STATUSES, name="user_status"), nullable=False, default="pending")
    invited_by   = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    password_hash = Column(Text, nullable=True)  # bcrypt hash
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    organisation   = relationship("Organisation", back_populates="users")
    otp_codes      = relationship("OtpCode",     back_populates="user", cascade="all, delete")
    manual_entries = relationship("ManualEntry", back_populates="user", cascade="all, delete")

    __table_args__ = (UniqueConstraint("org_id","email", name="uq_org_email"),)


# ── otp_codes ──────────────────────────────────────────────────────────────────
class OtpCode(Base):
    __tablename__ = "otp_codes"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id    = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash  = Column(String(200), nullable=False)   # never store plain OTP
    expires_at = Column(DateTime,   nullable=False)
    used       = Column(Boolean,    default=False)
    created_at = Column(DateTime,   default=now)

    user = relationship("User", back_populates="otp_codes")


# ── jira_tickets ───────────────────────────────────────────────────────────────
class JiraTicket(Base):
    __tablename__ = "jira_tickets"

    id                       = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id                   = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    jira_key                 = Column(String(50),  nullable=False)
    project_key              = Column(String(50),  nullable=False)
    project_name             = Column(String(200), nullable=True)
    summary                  = Column(Text,        nullable=False)
    assignee                 = Column(String(200), nullable=True)
    assignee_email           = Column(String(200), nullable=True)
    status                   = Column(String(100), nullable=True)
    client                   = Column(String(200), nullable=True)
    pod                      = Column(String(100), nullable=True)
    issue_type               = Column(String(100), nullable=True)
    priority                 = Column(String(50),  nullable=True)
    hours_spent              = Column(Float, default=0)
    original_estimate_hours  = Column(Float, default=0)
    remaining_estimate_hours = Column(Float, default=0)
    jira_created             = Column(Date, nullable=True)
    jira_updated             = Column(Date, nullable=True)
    url                      = Column(String(500), nullable=True)
    synced_at                = Column(DateTime, default=now, onupdate=now)

    organisation = relationship("Organisation", back_populates="jira_tickets")
    worklogs     = relationship("Worklog", back_populates="ticket", cascade="all, delete")

    __table_args__ = (
        UniqueConstraint("org_id","jira_key", name="uq_org_jira_key"),
        Index("ix_jt_org_updated",  "org_id","jira_updated"),
        Index("ix_jt_assignee",     "org_id","assignee"),
        Index("ix_jt_pod",          "org_id","pod"),
        Index("ix_jt_client",       "org_id","client"),
        Index("ix_jt_project",      "org_id","project_key"),
    )


# ── worklogs ───────────────────────────────────────────────────────────────────
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
        Index("ix_wl_ticket",   "ticket_id"),
        Index("ix_wl_date",     "log_date"),
        Index("ix_wl_author",   "author"),
    )


# ── manual_entries ─────────────────────────────────────────────────────────────
ENTRY_TYPES    = ["Meeting", "Bugs", "Feature", "Program Management"]
ENTRY_STATUSES = ["draft","confirmed","approved"]

class ManualEntry(Base):
    __tablename__ = "manual_entries"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id      = Column(UUID(as_uuid=False), ForeignKey("users.id",         ondelete="CASCADE"), nullable=False)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    entry_date   = Column(Date,        nullable=False)
    activity     = Column(String(500), nullable=False)
    hours        = Column(Float,       nullable=False)
    pod          = Column(String(100), nullable=True)
    client       = Column(String(200), nullable=True)
    entry_type   = Column(SAEnum(*ENTRY_TYPES,    name="entry_type"),   default="Meeting")
    notes        = Column(Text, nullable=True)
    ai_raw_input = Column(Text, nullable=True)   # raw text user typed in AI box
    ai_parsed    = Column(Boolean, default=True)
    status       = Column(SAEnum(*ENTRY_STATUSES, name="entry_status"), default="confirmed")
    created_at   = Column(DateTime, default=now)
    updated_at   = Column(DateTime, default=now, onupdate=now)

    user         = relationship("User",         back_populates="manual_entries")
    organisation = relationship("Organisation", back_populates="manual_entries")

    __table_args__ = (
        Index("ix_me_user_date",  "user_id","entry_date"),
        Index("ix_me_org_date",   "org_id", "entry_date"),
        Index("ix_me_pod",        "org_id", "pod"),
        Index("ix_me_client",     "org_id", "client"),
    )


# ── sync_log ───────────────────────────────────────────────────────────────────
SYNC_STATUSES = ["running","success","failed"]

class SyncLog(Base):
    __tablename__ = "sync_log"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id          = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    started_at      = Column(DateTime, default=now)
    finished_at     = Column(DateTime, nullable=True)
    status          = Column(SAEnum(*SYNC_STATUSES, name="sync_status"), default="running")
    tickets_synced  = Column(Integer, default=0)
    worklogs_synced = Column(Integer, default=0)
    error           = Column(Text, nullable=True)

    organisation = relationship("Organisation", back_populates="sync_logs")

    __table_args__ = (Index("ix_sl_org_started","org_id","started_at"),)


# ── Create / Drop ──────────────────────────────────────────────────────────────
def create_tables():
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created")

def drop_tables():
    Base.metadata.drop_all(bind=engine)
    print("🗑️  All tables dropped")

if __name__ == "__main__":
    create_tables()