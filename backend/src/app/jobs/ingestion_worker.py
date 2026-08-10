"""Ingestion worker service (the missing job-queue handler).

Claims ``PENDING`` ingestion jobs from the PostgreSQL-backed queue and runs
the full pipeline per job:

    claim (FOR UPDATE SKIP LOCKED) -> PROCESSING
      -> read source bytes from MinIO (object_key)
      -> validate -> parse -> normalize -> chunk   (ingestion engine)
      -> embed leaves via the Model Gateway embedder
      -> persist chunks + provenance                 (ORM persist adapter)
      -> INDEXED

Failures are recorded **in place** on the same ``document_version`` /
``ingestion_job`` rows (``FAILED`` + ``failure_reason`` + ``error_message``)
so a failed job can be retried without re-uploading the source document
(contract §5, retry-in-place).

Run with::

    python -m app.jobs.ingestion_worker

The compose ``worker`` service uses the same image as the backend with this
command.
"""

import asyncio
import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppSettings, get_settings
from app.db import session as db_session
from app.integrations.object_store import ObjectStore, ObjectStoreError, S3ObjectStore
from app.knowledge.ingestion.parse import IngestionFailed, build_normalized
from app.knowledge.ingestion.persist import (
    failure_reason_for,
    find_indexed_version_by_checksum,
    mark_failed,
    persist_indexed,
    utcnow,
)
from app.knowledge.models import (
    Document,
    DocumentVersion,
    FailureReason,
    IngestionJob,
    IngestionStatus,
)
from app.model_gateway.factory import build_embedder
from app.model_gateway.interfaces import Embedder

logger = logging.getLogger(__name__)


def _artifact_key(document_version_id: UUID) -> str:
    return f"artifacts/{document_version_id}.json"


async def _load_previous_artifact(
    session: AsyncSession,
    object_store: ObjectStore,
    version: DocumentVersion,
) -> dict | None:
    """The previous version's normalized artifact, if it was persisted.

    Used for the chunk-hash version diff (``change_summary``) so re-indexing
    reports unchanged/changed/added/removed leaves without reparsing the
    previous source (contract §5: normalized artifacts are reusable).
    """
    if version.previous_version_id is None:
        return None
    try:
        raw = await object_store.get_bytes(_artifact_key(version.previous_version_id))
    except ObjectStoreError:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


async def claim_next_jobs(session: AsyncSession, limit: int) -> list[IngestionJob]:
    """Atomically claim up to ``limit`` PENDING jobs.

    ``FOR UPDATE SKIP LOCKED`` makes concurrent workers safe: a job is only
    ever claimed by one worker, and the lock never blocks other workers.
    """
    stmt = (
        select(IngestionJob)
        .where(IngestionJob.status == IngestionStatus.PENDING)
        .order_by(IngestionJob.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    jobs = list((await session.execute(stmt)).scalars().all())
    for job in jobs:
        job.status = IngestionStatus.PROCESSING
        job.started_at = utcnow()
    await session.commit()
    return jobs


async def process_job(
    session: AsyncSession,
    job_id: UUID,
    object_store: ObjectStore,
    embedder: Embedder,
) -> dict:
    """Process one claimed job end to end and return a JSON summary.

    ``job_id`` is the ``ingestion_job_id``. The caller owns the session
    (one session per job in the loop) so a crash mid-job never leaves a
    half-committed transaction across jobs.
    """
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise ValueError(f"ingestion job {job_id} not found")
    version = await session.get(DocumentVersion, job.document_version_id)
    if version is None:
        raise ValueError(f"document version for job {job_id} not found")
    document = await session.get(Document, version.document_id)
    if document is None:
        raise ValueError(f"document for job {job_id} not found")
    filename = version.original_filename

    async def _fail(reason: FailureReason, message: str) -> dict:
        # Drop any partial rows from this attempt, then record the FAILED
        # lifecycle in place (retryable).
        await session.rollback()
        await mark_failed(
            session, document=document, version=version, job=job,
            reason=reason, message=message,
        )
        logger.warning("job %s FAILED (%s): %s", job_id, reason.value, message)
        return {
            "status": "FAILED",
            "ingestion_job_id": str(job_id),
            "failure_reason": reason.value,
            "error_message": (message or "")[:4000],
        }

    # 1. Source bytes from MinIO (authoritative object_key).
    try:
        data = await object_store.get_bytes(version.object_key)
    except ObjectStoreError as exc:
        return await _fail(FailureReason.STORAGE_ERROR, str(exc))

    # 2. Dedup backstop (checked again at upload; at-least-once safety).
    duplicate = await find_indexed_version_by_checksum(session, version.checksum)
    if duplicate is not None and duplicate.document_version_id != version.document_version_id:
        await session.rollback()
        job.status = IngestionStatus.INDEXED
        job.completed_at = utcnow()
        version.status = "INDEXED"
        document.status = "INDEXED"
        await session.commit()
        logger.info("job %s SKIPPED_DUPLICATE -> %s", job_id, duplicate.document_version_id)
        return {
            "status": "SKIPPED_DUPLICATE",
            "ingestion_job_id": str(job_id),
            "document_version_id": str(duplicate.document_version_id),
            "checksum": version.checksum[:12],
        }

    # 3. validate -> parse -> normalize -> chunk (in-memory engine seam),
    #    diffed against the previous version's artifact when one exists.
    previous_artifact = await _load_previous_artifact(session, object_store, version)
    try:
        artifact = build_normalized(
            data, filename=filename, file_path=filename, previous_artifact=previous_artifact
        )
    except IngestionFailed as exc:
        return await _fail(failure_reason_for(exc), f"{exc.code}: {exc.reason}")

    # 4. Embed leaves via the Model Gateway (L2-normalized upstream).
    leaves = [c for c in artifact["chunks"] if c.get("embeddable")]
    try:
        vectors = await embedder.embed(
            [c["processed_content"] for c in leaves], prefix="search_document: "
        )
    except Exception as exc:  # noqa: BLE001 - network/model failure -> EMBEDDING_ERROR
        return await _fail(FailureReason.EMBEDDING_ERROR, str(exc))
    embeddings_by_index = {
        c["chunk_index"]: vec for c, vec in zip(leaves, vectors, strict=True)
    }

    # 5. Persist chunks + provenance, flip lifecycle to INDEXED.
    try:
        summary = await persist_indexed(
            session,
            document=document,
            version=version,
            job=job,
            artifact=artifact,
            embeddings_by_index=embeddings_by_index,
            embedder_model=getattr(embedder, "model", getattr(embedder, "model_name", "unknown")),
            embedder_version=getattr(embedder, "version", ""),
        )
    except Exception as exc:  # noqa: BLE001 - any persist error -> FAILED lifecycle
        return await _fail(failure_reason_for(exc), str(exc))

    # 6. Persist the normalized artifact for reuse on the next re-index
    #    (contract §5). A failure here is not fatal: the chunk rows are
    #    already committed and INDEXED; the diff just degrades to None next
    #    time.
    try:
        await object_store.put_bytes(
            _artifact_key(version.document_version_id),
            json.dumps(artifact, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
    except ObjectStoreError:
        logger.warning(
            "job %s: could not persist normalized artifact %s",
            job_id,
            _artifact_key(version.document_version_id),
        )
    return summary


async def retry_job(session: AsyncSession, job_id: UUID) -> dict:
    """Reset a FAILED job (+ its version/document) to PENDING for in-place retry.

    The MinIO source is untouched; the same version row is reprocessed.
    """
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise ValueError(f"ingestion job {job_id} not found")
    if job.status != IngestionStatus.FAILED:
        raise ValueError(f"job {job_id} is {job.status.value}; only FAILED jobs can be retried")
    version = await session.get(DocumentVersion, job.document_version_id)
    document = await session.get(Document, version.document_id) if version else None

    job.status = IngestionStatus.PENDING
    job.failure_reason = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    if version is not None:
        version.status = "PENDING"
    if document is not None:
        document.status = "PENDING"
    await session.commit()
    return {
        "status": "PENDING",
        "ingestion_job_id": str(job_id),
        "document_version_id": str(job.document_version_id),
    }


async def run_worker(
    settings: AppSettings | None = None,
    *,
    object_store: ObjectStore | None = None,
    embedder: Embedder | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Poll the queue forever, processing claimed jobs (at-least-once).

    ``object_store`` / ``embedder`` are injectable for tests; defaults are
    the real MinIO adapter and the Model Gateway embedder.
    """
    settings = settings or get_settings()
    object_store = object_store or S3ObjectStore(settings.minio)
    embedder = embedder or build_embedder(settings)
    poll = settings.ingestion.poll_interval_seconds
    limit = settings.ingestion.max_jobs_per_pass
    logger.info("ingestion worker started (poll=%ss, batch=%s)", poll, limit)

    while stop_event is None or not stop_event.is_set():
        jobs: list[IngestionJob] = []
        try:
            async with db_session.async_session_factory() as session:
                jobs = await claim_next_jobs(session, limit)
            for job in jobs:
                async with db_session.async_session_factory() as session:
                    summary = await process_job(
                        session, job.ingestion_job_id, object_store, embedder
                    )
                    logger.info("job %s -> %s", job.ingestion_job_id, summary.get("status"))
        except asyncio.CancelledError:
            logger.info("ingestion worker stopping")
            raise
        except Exception:
            logger.exception("ingestion worker loop error")
        if not jobs:
            await asyncio.sleep(poll)


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await run_worker()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
