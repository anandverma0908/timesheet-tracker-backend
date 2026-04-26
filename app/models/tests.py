from sqlalchemy import Column, String, Text, Boolean, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.base import Base, gen_uuid, now


class TestCase(Base):
    __tablename__ = "test_cases"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id        = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod           = Column(String(100), nullable=False)
    ticket_id     = Column(UUID(as_uuid=False), ForeignKey("jira_tickets.id", ondelete="SET NULL"), nullable=True)
    ticket_key    = Column(String(50), nullable=True)
    title         = Column(String(500), nullable=False)
    description   = Column(Text, nullable=True)
    preconditions = Column(Text, nullable=True)
    steps         = Column(JSONB, nullable=True)  # [{step, expected_result}]
    priority      = Column(String(20), default="medium", nullable=False)
    status        = Column(String(20), default="active", nullable=False)
    ai_generated  = Column(Boolean, default=False, nullable=False)
    created_by    = Column(String(200), nullable=True)
    created_at    = Column(DateTime, default=now)
    updated_at    = Column(DateTime, default=now, onupdate=now)

    __table_args__ = (
        Index("ix_testcase_org_pod", "org_id", "pod"),
        Index("ix_testcase_ticket", "ticket_id"),
    )


class TestCycle(Base):
    __tablename__ = "test_cycles"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id      = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    pod         = Column(String(100), nullable=False)
    name        = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    sprint_id   = Column(String(100), nullable=True)
    release_id  = Column(String(100), nullable=True)
    status      = Column(String(20), default="planning", nullable=False)
    created_by  = Column(String(200), nullable=True)
    created_at  = Column(DateTime, default=now)
    updated_at  = Column(DateTime, default=now, onupdate=now)

    __table_args__ = (
        Index("ix_tcycle_org_pod", "org_id", "pod"),
        Index("ix_tcycle_status", "org_id", "pod", "status"),
    )


class TestExecution(Base):
    __tablename__ = "test_executions"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    cycle_id     = Column(UUID(as_uuid=False), ForeignKey("test_cycles.id", ondelete="CASCADE"), nullable=False)
    test_case_id = Column(UUID(as_uuid=False), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    status       = Column(String(20), default="pending", nullable=False)
    executed_by  = Column(String(200), nullable=True)
    notes        = Column(Text, nullable=True)
    executed_at  = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=now)
    updated_at   = Column(DateTime, default=now, onupdate=now)

    __table_args__ = (
        Index("ix_texec_cycle", "cycle_id"),
        Index("ix_texec_case", "test_case_id"),
    )
