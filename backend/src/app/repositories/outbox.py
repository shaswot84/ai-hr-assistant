from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.outbox import OutboxJob
from app.shared.clock import Clock, get_clock


class OutboxRepo:
    """Data access for the transactional outbox job table."""

    def __init__(self, db: AsyncSession, clock: Clock | None = None) -> None:
        """Bind the repository to an async DB session and (optionally) a Clock."""
        self._db = db
        self._clock = clock or get_clock()

    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        *,
        aggregate_type: str | None = None,
        aggregate_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> OutboxJob:
        """Create a PENDING outbox job in the current (caller-managed) transaction."""
        now = self._clock.now()
        job = OutboxJob(
            job_type=job_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        self._db.add(job)
        await self._db.flush()
        return job

    async def claim_next(self) -> OutboxJob | None:
        """Atomically claim the oldest due PENDING job for processing."""
        now = self._clock.now()
        stmt = (
            select(OutboxJob)
            .where(OutboxJob.status == "PENDING", OutboxJob.available_at <= now)
            .order_by(OutboxJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = await self._db.scalar(stmt)
        if job is not None:
            job.status = "RUNNING"
            job.attempt_count += 1
            job.updated_at = now
            await self._db.flush()
        return job

    async def mark_succeeded(self, job: OutboxJob) -> None:
        """Mark a job as SUCCEEDED after it completed successfully."""
        now = self._clock.now()
        job.status = "SUCCEEDED"
        job.processed_at = now
        job.updated_at = now
        await self._db.flush()

    async def mark_failed(self, job: OutboxJob, error: str) -> None:
        """Mark a job FAILED (or re-queue it PENDING if attempts remain), recording the error."""
        now = self._clock.now()
        job.last_error = error[:1000]
        job.updated_at = now
        job.status = "PENDING" if job.attempt_count < job.max_attempts else "FAILED"
        if job.status == "FAILED":
            job.processed_at = now
        await self._db.flush()

