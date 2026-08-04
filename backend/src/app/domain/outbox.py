from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxJob(Base):
    """PostgreSQL-backed job/outbox written in the same transaction as the business change."""

    __tablename__ = "outbox_job"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(100))  # EVALUATE_APPLICATION | SEND_EMAIL
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING|RUNNING|SUCCEEDED|FAILED
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))