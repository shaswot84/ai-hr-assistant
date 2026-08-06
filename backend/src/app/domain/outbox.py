from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxJob(Base):
    """PostgreSQL-backed job/outbox written in the same transaction as the business change.

    Claimed with ``SELECT ... FOR UPDATE SKIP LOCKED`` (see
    ``repositories/outbox.py``) so concurrent worker replicas never process
    the same job twice.
    """

    __tablename__ = "outbox_job"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(100))  # EVALUATE_APPLICATION | SEND_*
    aggregate_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING|RUNNING|SUCCEEDED|FAILED
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_outbox_status_available", OutboxJob.status, OutboxJob.available_at)
