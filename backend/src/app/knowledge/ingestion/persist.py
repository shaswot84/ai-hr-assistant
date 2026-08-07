"""Postgres/ORM persist adapter for the ingestion pipeline.

Replaces the SQLite dev writer (``db_write.py``). Consumes a
``normalized_document_v2`` artifact plus the leaf embeddings produced by the
Model Gateway embedder, and writes the contract rows via the ORM
(``knowledge/models.py``):

- ``document_chunk`` rows with the correct ``parent_chunk_id`` / ``ancestors``
  chain and pgvector embeddings (leaf rows only),
- lifecycle flips on ``document_version`` / ``ingestion_job`` / ``document``
  to ``INDEXED``,
- ``is_current`` flip + ``previous_version_id``/``change_summary`` for
  version-bump and re-index.

Hard rule (contract §3): query-time scores (BM25 / cosine / RRF / reranker /
confidence) are **never** written. This module only persists content,
provenance, and lifecycle state.
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.object_store import ObjectStoreError
from app.knowledge.ingestion.parse import ChunkingError, IngestionFailed
from app.knowledge.models import (
    Document,
    DocumentChunk,
    DocumentVersion,
    FailureReason,
    IngestionJob,
    IngestionStatus,
)

logger = logging.getLogger(__name__)

SCHEMA = "normalized_document_v2"


def utcnow() -> datetime:
    return datetime.now(UTC)


def failure_reason_for(exc: Exception) -> FailureReason:
    """Map an ingestion-stage exception to the coarse failure enum.

    Order matters: :class:`ChunkingError` subclasses :class:`IngestionFailed`,
    so it must be checked first.
    """
    if isinstance(exc, ChunkingError):
        return FailureReason.CHUNKING_ERROR
    if isinstance(exc, IngestionFailed):
        return FailureReason.PARSING_ERROR
    if isinstance(exc, ObjectStoreError):
        return FailureReason.STORAGE_ERROR
    if isinstance(exc, TimeoutError):
        return FailureReason.TIMEOUT
    return FailureReason.UNKNOWN


async def find_indexed_version_by_checksum(
    session: AsyncSession, checksum: str
) -> DocumentVersion | None:
    """The INDEXED version holding ``checksum``, if any (dedup key).

    The partial unique index ``uq_version_checksum_indexed`` guarantees at
    most one such row, so identical bytes are never indexed twice.
    """
    stmt = (
        select(DocumentVersion)
        .where(DocumentVersion.checksum == checksum, DocumentVersion.status == "INDEXED")
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def persist_indexed(
    session: AsyncSession,
    *,
    document: Document,
    version: DocumentVersion,
    job: IngestionJob,
    artifact: dict,
    embeddings_by_index: dict[int, list[float]],
    embedder_model: str,
    embedder_version: str,
) -> dict:
    """Write a NORMALIZED artifact's chunk tree for ``version`` and mark the
    lifecycle ``INDEXED``. Returns a JSON-serializable summary (no scores).

    The caller must have already loaded ``document`` / ``version`` / ``job``
    and set ``job.status = PROCESSING``. On any error this function raises
    after rolling back partial chunk rows; the caller decides whether to
    record a FAILED lifecycle (see the worker).
    """
    if artifact.get("schema") != SCHEMA:
        raise ValueError(f"unsupported artifact schema: {artifact.get('schema')!r}")
    meta = artifact.get("metadata") or {}
    if meta.get("status") != "NORMALIZED":
        raise ValueError(
            f"only NORMALIZED artifacts can be written (got status={meta.get('status')!r})"
        )
    chunks = artifact.get("chunks") or []
    if not chunks:
        raise ValueError("artifact has no chunks; a NORMALIZED artifact must be chunked")
    for c in chunks:
        if not c.get("content_hash_sha256"):
            raise ValueError(
                f"chunk {c.get('chunk_index')} is missing content_hash_sha256"
            )

    # Retry-in-place / re-index: replace this version's derived rows. The
    # MinIO source is never touched (contract invariant #6).
    await session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.document_version_id == version.document_version_id
        )
    )

    # The artifact's parent_chunk_id / ancestors are chunk *indices* (as in
    # db_write.py); resolve them to the stable chunk_ids we assign here.
    chunk_ids: dict[int, uuid.UUID] = {c["chunk_index"]: uuid.uuid4() for c in chunks}

    for c in chunks:
        embeddable = bool(c.get("embeddable", True))
        parent_hint = c.get("parent_chunk_id")
        parent_id = chunk_ids.get(parent_hint) if parent_hint is not None else None
        ancestors = c.get("ancestors") or []
        ancestor_ids = [str(chunk_ids[a]) for a in ancestors if a in chunk_ids] or None
        path = c.get("section_path") or []
        session.add(
            DocumentChunk(
                chunk_id=chunk_ids[c["chunk_index"]],
                document_version_id=version.document_version_id,
                chunk_index=c["chunk_index"],
                chunk_level=c.get("chunk_level") or ("leaf" if embeddable else "context"),
                parent_chunk_id=parent_id,
                ancestors=ancestor_ids,
                embeddable=embeddable,
                content=c.get("content"),
                processed_content=c.get("processed_content"),
                original_content=c.get("original_content"),
                page_number=c.get("page_number"),
                section_title=c.get("parent_section"),
                section_path=" > ".join(path) if path else None,
                token_count=c.get("token_count"),
                # Context (document/section) rows never carry an embedding,
                # even when their content hash collides with a leaf row's.
                embedding=embeddings_by_index.get(c["chunk_index"]) if embeddable else None,
            )
        )

    # Provenance (the fields the Knowledge Service reads on every hit).
    chunker = meta.get("chunker") or {}
    job.status = IngestionStatus.INDEXED
    job.parser_version = meta.get("parser_version")
    job.chunking_strategy = chunker.get("strategy")
    job.embedding_model = embedder_model
    job.embedding_version = embedder_version
    job.pipeline_version = meta.get("pipeline_version")
    job.started_at = job.started_at or utcnow()
    job.completed_at = utcnow()
    job.failure_reason = None
    job.error_message = None

    # Version-bump / re-index lifecycle.
    version.status = "INDEXED"
    version.is_current = True
    vd = artifact.get("version_diff")
    if vd and vd.get("stats"):
        version.change_summary = json.dumps(vd["stats"])
    version.checksum = meta["content_hash_sha256"]
    version.file_size = meta.get("size_bytes", version.file_size)
    if meta.get("format"):
        version.mime_type = meta["format"]
    # object_key is deliberately untouched: re-index never rewrites MinIO.
    await session.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.document_id == document.document_id,
            DocumentVersion.document_version_id != version.document_version_id,
        )
        .values(is_current=False)
    )

    document.status = "INDEXED"
    # NB: document.title is deliberately NOT rewritten from the artifact's
    # first heading — the registry name (upload title) is the stable identity
    # the upload orchestration matches on for version bumps.

    await session.commit()

    return {
        "status": "INDEXED",
        "document_id": str(document.document_id),
        "document_version_id": str(version.document_version_id),
        "version_number": version.version_number,
        "checksum": meta["content_hash_sha256"][:12],
        "tree_rows": len(chunks),
        "embeddable_chunks": sum(1 for c in chunks if c.get("embeddable", True)),
        "embedded": len(embeddings_by_index),
        "embedding_model": embedder_model,
    }


async def mark_failed(
    session: AsyncSession,
    *,
    document: Document,
    version: DocumentVersion,
    job: IngestionJob,
    reason: FailureReason,
    message: str | None,
) -> None:
    """Record a FAILED lifecycle in place (retryable without re-upload).

    The version keeps its rows (if any) but is never served: the read side
    filters on ``INDEXED`` only. ``is_current`` stays False on failure so a
    previously INDEXED version of the document remains servable.
    """
    job.status = IngestionStatus.FAILED
    job.failure_reason = reason
    job.error_message = (message or "")[:4000] or None
    job.completed_at = utcnow()
    version.status = "FAILED"
    document.status = "FAILED"
    await session.commit()
