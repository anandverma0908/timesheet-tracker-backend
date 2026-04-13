from sqlalchemy import Column, String, Text, Integer, Numeric, DateTime, Index, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, gen_uuid, now


class ClientBudget(Base):
    __tablename__ = "client_budgets"

    id           = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id       = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    client       = Column(Text,    nullable=False)
    month        = Column(Integer, nullable=False)
    year         = Column(Integer, nullable=False)
    budget_hours = Column(Numeric, nullable=False)
    created_at   = Column(DateTime, default=now)

    __table_args__ = (
        UniqueConstraint("org_id", "client", "month", "year", name="uq_budget_org_client_month"),
    )


class BurnRateAlert(Base):
    __tablename__ = "burn_rate_alerts"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    org_id        = Column(UUID(as_uuid=False), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    client        = Column(Text,    nullable=False)
    threshold_pct = Column(Integer, nullable=False)   # 70 | 85 | 100 | 110
    hours_used    = Column(Numeric, nullable=True)
    hours_budget  = Column(Numeric, nullable=True)
    nova_summary  = Column(Text,    nullable=True)
    notified_at   = Column(DateTime, default=now)

    __table_args__ = (Index("ix_bra_org", "org_id", "notified_at"),)
