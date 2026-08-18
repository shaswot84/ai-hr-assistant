"""Upload + Document Registry orchestration.

The entry point for both ingestion sources (administrator upload and
approved Knowledge Review Tasks — they differ only in provenance, never in
processing, per ``ingestion.md`` §2.1).

What happens here, in order:

1. SHA-256 checksum dedup — identical bytes already INDEXED anywhere are
   skipped (``SKIPPED_DUPLICATE``), no new version/job is created.
2. Document Registry row — find the logical ``document`` by title or create
   it; bump ``version_number``; set ``previous_version_id`` to the last
   INDEXED version of the document.
3. Store the **original bytes** in MinIO (authoritative ``object_key``)
   *before* committing the job, so the worker never claims a job whose
   source is missing.
4. Enqueue a ``PENDING`` ``ingestion_job`` that the worker consumes.

The document/version/job statuses start at ``PENDING`` (the read side only
serves ``INDEXED``, so nothing mid-flight is ever retrievable).
"""

import hashlib
import logging
import mimetypes
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.object_store import ObjectStore, ObjectStoreError
from app.knowledge.ingestion.persist import find_indexed_version_by_checksum
from app.knowledge.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    IngestionStatus,
)

logger = logging.getLogger(__name__)


class DuplicateDocumentError(Exception):
    """Raised when the same bytes are already INDEXED (HTTP 409)."""

    def __init__(self, document_version_id: uuid.UUID) -> None:
        super().__init__("identical document already indexed")
        self.document_version_id = document_version_id


async def register_document(
    session: AsyncSession,
    object_store: ObjectStore,
    *,
    filename: str,
    data: bytes,
    category: DocumentCategory,
    document_type: str = "OTHER",
    description: str | None = None,
    uploaded_by: uuid.UUID | None = None,
    role_access: list[str] | None = None,
) -> dict:
    """Register an uploaded document and enqueue its ingestion job.

    Returns a JSON-serializable summary with ``status`` = ``PENDING``
    (enqueued) or ``SKIPPED_DUPLICATE`` (identical bytes already indexed).
    Raises :class:`DuplicateDocumentError` when ``skip_duplicate`` is set
    (not used by the default path — the API maps the returned status).

    ``role_access`` is the uploader-chosen allowlist of roles that may
    retrieve the document; ``None`` keeps the model default (all roles).
    """
    checksum = hashlib.sha256(data).hexdigest()

    # 1. Checksum dedup (contract §2 / versioning §6).
    existing = await find_indexed_version_by_checksum(session, checksum)
    if existing is not None:
        return {
            "status": "SKIPPED_DUPLICATE",
            "document_id": str(existing.document_id),
            "document_version_id": str(existing.document_version_id),
            "version_number": existing.version_number,
            "checksum": checksum[:12],
        }

    # 2. Document Registry row (match by title like db_write.py).
    name = os.path.splitext(filename)[0]
    document = (
        await session.execute(
            select(Document)
            .where(Document.title == name, Document.deleted_at.is_(None))
            .limit(1)
        )
    ).scalar_one_or_none()
    if document is None:
        document = Document(
            title=name,
            document_type=document_type,
            category=category,
            description=description,
            status="PENDING",
            created_by=uploaded_by,
        )
        if role_access is not None:
            document.role_access = role_access
        session.add(document)
        await session.flush()
    elif role_access is not None:
        document.role_access = role_access

    # 3. Version row: bump version_number, link the previous INDEXED version.
    max_version = (
        await session.execute(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document.document_id
            )
        )
    ).scalar()
    version_number = int(max_version or 0) + 1

    version = DocumentVersion(
        document_id=document.document_id,
        version_number=version_number,
        object_key=f"documents/{document.document_id}/{version_number}/{filename}",
        original_filename=filename,
        mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        file_size=len(data),
        checksum=checksum,
        is_current=False,
        uploaded_by=uploaded_by,
        status="PENDING",
    )
    session.add(version)
    await session.flush()

    previous = (
        await session.execute(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.document_id,
                DocumentVersion.document_version_id != version.document_version_id,
                DocumentVersion.status == "INDEXED",
            )
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if previous is not None:
        version.previous_version_id = previous.document_version_id

    # 4. Enqueue the job BEFORE the MinIO write is committed to the DB, then
    #    store the bytes. If storage fails, nothing is committed -> no orphan
    #    registry rows and no job that can never be satisfied.
    job = IngestionJob(
        document_version_id=version.document_version_id,
        status=IngestionStatus.PENDING,
    )
    session.add(job)
    try:
        await object_store.put_bytes(version.object_key, data, version.mime_type)
    except ObjectStoreError:
        await session.rollback()
        raise
    await session.flush()
    await session.commit()

    return {
        "status": "PENDING",
        "document_id": str(document.document_id),
        "document_version_id": str(version.document_version_id),
        "ingestion_job_id": str(job.ingestion_job_id),
        "version_number": version_number,
        "checksum": checksum[:12],
        "object_key": version.object_key,
    }


class DocumentNotFoundError(Exception):
    """Raised when the document to delete does not exist (HTTP 404)."""


async def _document_object_keys(session: AsyncSession, document_id: uuid.UUID) -> list[str]:
    """All MinIO object keys belonging to a document (any version)."""
    return list(
        (
            await session.execute(
                select(DocumentVersion.object_key).where(
                    DocumentVersion.document_id == document_id
                )
            )
        )
        .scalars()
        .all()
    )


async def _remove_objects(object_store: ObjectStore, keys: list[str]) -> dict[str, int]:
    """Best-effort MinIO removal: never raises, returns ``{removed, failed}``."""
    removed = 0
    failed = 0
    for key in keys:
        try:
            await object_store.delete_bytes(key)
            removed += 1
        except ObjectStoreError as exc:
            logger.warning("object store cleanup failed for %s: %s", key, exc)
            failed += 1
    return {"removed": removed, "failed": failed}


async def soft_delete_document(
    session: AsyncSession,
    object_store: ObjectStore,
    document_id: uuid.UUID,
) -> dict:
    """Soft-delete a document: tombstone it in the DB, then best-effort
    remove its authoritative bytes from MinIO.

    The document, versions, chunks and jobs stay in Postgres (audit/undo),
    but every read path filters on ``deleted_at`` (registry listing, detail,
    retrieval). The MinIO bytes are deleted because they are the only
    copy of the source file — leaving them would orphan storage.
    """
    document = await session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise DocumentNotFoundError(f"document {document_id} not found")

    keys = await _document_object_keys(session, document_id)
    document.deleted_at = datetime.now(UTC)
    document.status = "DELETED"
    await session.commit()

    removal = await _remove_objects(object_store, keys)
    return {
        "document_id": str(document_id),
        "status": "DELETED",
        "deleted_at": document.deleted_at.isoformat(),
        "versions_removed": len(keys),
        **removal,
    }


async def clear_all_documents(
    session: AsyncSession,
    object_store: ObjectStore,
) -> dict:
    """Hard-delete every document and its related data (demo reset).

    Removes documents, versions, chunks (incl. pgvector embeddings + FTS
    rows), ingestion jobs, and the authoritative bytes from MinIO — a full
    wipe so the pipeline can be demoed from scratch. The checksum dedup
    backstop (``uq_version_checksum_indexed``) means re-uploading the same
    bytes afterwards indexes cleanly again.
    """
    doc_ids = list(
        (await session.execute(select(Document.document_id))).scalars().all()
    )
    if not doc_ids:
        return {"deleted_documents": 0, "removed_objects": 0}

    keys = list(
        (
            await session.execute(
                select(DocumentVersion.object_key).where(
                    DocumentVersion.document_id.in_(doc_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    # Delete children first (ingestion_job -> document_chunk -> document_version),
    # then the documents themselves. No FK-level CASCADE in the schema, so the
    # ORM delete-orphan relationships do the work via explicit deletes.
    await session.execute(
        delete(IngestionJob).where(
            IngestionJob.document_version_id.in_(
                select(DocumentVersion.document_version_id).where(
                    DocumentVersion.document_id.in_(doc_ids)
                )
            )
        )
    )
    await session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.document_version_id.in_(
                select(DocumentVersion.document_version_id).where(
                    DocumentVersion.document_id.in_(doc_ids)
                )
            )
        )
    )
    await session.execute(
        update(DocumentVersion)
        .where(DocumentVersion.document_id.in_(doc_ids))
        .values(previous_version_id=None)
    )
    await session.execute(
        delete(DocumentVersion).where(DocumentVersion.document_id.in_(doc_ids))
    )
    await session.execute(delete(Document).where(Document.document_id.in_(doc_ids)))
    await session.commit()

    removal = await _remove_objects(object_store, keys)
    return {
        "deleted_documents": len(doc_ids),
        "removed_objects": len(keys),
        **removal,
    }
