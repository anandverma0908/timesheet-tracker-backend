"""
app/models/base.py — Shared SQLAlchemy base and helpers.
Import Base from here in every model file.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from app.core.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.utcnow()


class TimestampMixin:
    """Adds created_at / updated_at to any model."""
    created_at = Column(DateTime, default=now, nullable=False)
    updated_at = Column(DateTime, default=now, onupdate=now, nullable=False)
