from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.outbox import OutboxJob


class OutboxRepo:
    """Data access for the transactional outbox job table."""

    def __init__(self, db: Session) -> None:
        """Bind the repository to a DB session."""
        self._db = db

    def enqueue(self, job_type: str, payload: dict, max_attempts: int = 3) -> OutboxJob:
        """Create a PENDING outbox job in the current (caller-managed) transaction."""
        now = datetime.now(UTC)
        job = OutboxJob(
            job_type=job_type,
            status="PENDING",
            payload=payload,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
        )
        self._db.add(job)
        self._db.flush()
        return job

    def claim_next(self) -> OutboxJob | None:
        """Atomically claim the oldest pending job for processing."""
        stmt = (
            select(OutboxJob)
            .where(OutboxJob.status == "PENDING")
            .order_by(OutboxJob.created_at.asc())
            .limit(1)
        )
        job = self._db.scalar(stmt)
        if job is not None:
            job.status = "RUNNING"
            job.attempts += 1
            job.updated_at = datetime.now(UTC)
            self._db.flush()
        return job

    def mark_succeeded(self, job: OutboxJob) -> None:
        """Mark a job as SUCCEEDED after it completed successfully."""
        job.status = "SUCCEEDED"
        job.updated_at = datetime.now(UTC)
        self._db.flush()

    def mark_failed(self, job: OutboxJob, error: str) -> None:
        """Mark a job as FAILED, recording a truncated error message."""
        job.status = "FAILED"
        job.last_error = error[:1000]
        job.updated_at = datetime.now(UTC)
        self._db.flush()
