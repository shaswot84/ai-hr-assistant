"""Knowledge API: ingestion (upload/registry/jobs) + retrieval (search).

Write side:
- ``POST /api/knowledge/documents/upload`` — register + enqueue an ingestion
  job for an uploaded file (bytes go to MinIO; the worker indexes them).
- ``GET /api/knowledge/documents`` / ``GET /api/knowledge/documents/{id}`` —
  Document Registry listing/detail (lifecycle status included).
- ``GET /api/knowledge/jobs/{job_id}`` — ingestion job status/provenance.
- ``POST /api/knowledge/jobs/{job_id}/retry`` — retry a FAILED job in place.

Read side:
- ``GET /api/knowledge/search?q=...`` — the Knowledge Service hybrid
  retrieval (BM25 + vector, RRF, rerank, confidence, citations). Only
  INDEXED versions are ever served (repository gate).

B008 is the standard FastAPI pattern (``File``/``Form``/``Depends`` in
argument defaults); the framework treats them as parameter metadata.
"""


import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.db.session import get_session
from app.integrations.object_store import ObjectStoreError, S3ObjectStore
from app.jobs.ingestion_worker import retry_job as retry_ingestion_job
from app.knowledge.ingestion.orchestrator import (
    DocumentNotFoundError,
    clear_all_documents,
    register_document,
    soft_delete_document,
)
from app.knowledge.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    IngestionStatus,
)
from app.knowledge.repository import HybridRetrievalRepository
from app.knowledge.service import KnowledgeService
from app.model_gateway.factory import build_embedder, build_llm, build_reranker
from app.model_gateway.interfaces import LLM, Embedder, Reranker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_CATEGORY_VALUES = {c.value: c for c in DocumentCategory}


def _object_store():
    """MinIO-backed object store (lazily created, shared across requests)."""
    store = getattr(_object_store, "_store", None)
    if store is None:
        store = S3ObjectStore(get_settings().minio)
        _object_store._store = store
    return store


def _embedder() -> Embedder:
    """Model Gateway embedder singleton (Ollama by default)."""
    embedder = getattr(_embedder, "_embedder", None)
    if embedder is None:
        embedder = build_embedder()
        _embedder._embedder = embedder
    return embedder


def _reranker() -> Reranker:
    """Model Gateway reranker singleton (lazy: model loads on first search).

    Loaded once per process, not per request — the cross-encoder weights
    (and, on first use, their download) are expensive. Falls back to
    pass-through when disabled or the optional extra is missing.
    """
    reranker = getattr(_reranker, "_reranker", None)
    if reranker is None:
        reranker = build_reranker()
        _reranker._reranker = reranker
    return reranker


def _llm() -> LLM | None:
    """Generation LLM singleton (Ollama Cloud by default); None when disabled."""
    llm = getattr(_llm, "_llm", None)
    if llm is None:
        llm = build_llm()
        _llm._llm = llm
    return llm


def _parse_category(raw: str | None) -> DocumentCategory:
    if not raw:
        return DocumentCategory.OTHER
    try:
        return DocumentCategory(raw.upper())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"unknown category {raw!r}; expected one of {sorted(_CATEGORY_VALUES)}",
        ) from None


def _serialize_document(row: Document, versions: int, current_chunks: int) -> dict:
    return {
        "document_id": str(row.document_id),
        "title": row.title,
        "document_type": row.document_type,
        "category": row.category.value if isinstance(row.category, DocumentCategory) else str(row.category),
        "description": row.description,
        "status": row.status,
        "versions": versions,
        "current_chunks": current_chunks,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form("OTHER"),
    document_type: str = Form("OTHER"),
    description: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Register an uploaded document and enqueue its ingestion job."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    max_size = get_settings().ingestion.max_file_size_bytes
    if len(data) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"file is {len(data)} bytes; limit is {max_size}",
        )
    try:
        return await register_document(
            session,
            _object_store(),
            filename=file.filename or "document",
            data=data,
            category=_parse_category(category),
            document_type=document_type or "OTHER",
            description=description,
        )
    except ObjectStoreError as exc:
        raise HTTPException(status_code=503, detail=f"object storage unavailable: {exc}") from exc


@router.get("/documents")
async def list_documents(session: AsyncSession = Depends(get_session)) -> dict:
    """Document Registry listing with lifecycle status."""
    versions_subq = (
        select(func.count(DocumentVersion.document_version_id))
        .where(DocumentVersion.document_id == Document.document_id)
        .correlate(Document)
        .scalar_subquery()
        .label("versions")
    )
    current_chunks_subq = (
        select(func.count(DocumentChunk.chunk_id))
        .select_from(DocumentVersion)
        .join(
            DocumentChunk,
            DocumentChunk.document_version_id == DocumentVersion.document_version_id,
        )
        .where(
            DocumentVersion.document_id == Document.document_id,
            DocumentVersion.is_current.is_(True),
        )
        .correlate(Document)
        .scalar_subquery()
        .label("current_chunks")
    )
    stmt = (
        select(Document, versions_subq, current_chunks_subq)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.title)
    )
    rows = (await session.execute(stmt)).all()
    return {
        "documents": [
            _serialize_document(doc, versions, current_chunks)
            for doc, versions, current_chunks in rows
        ]
    }


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Soft-delete a document + best-effort removal of its MinIO bytes."""
    try:
        return await soft_delete_document(session, _object_store(), document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ObjectStoreError as exc:
        raise HTTPException(status_code=503, detail=f"object storage unavailable: {exc}") from exc


@router.delete("/documents")
async def delete_all_documents(session: AsyncSession = Depends(get_session)) -> dict:
    """Hard-delete every document and its related data (demo reset)."""
    try:
        return await clear_all_documents(session, _object_store())
    except ObjectStoreError as exc:
        raise HTTPException(status_code=503, detail=f"object storage unavailable: {exc}") from exc


@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Document detail: versions + ingestion jobs (provenance)."""
    document = await session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="document not found")

    versions = (
        (
            await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    version_ids = [v.document_version_id for v in versions]
    jobs = (
        (
            await session.execute(
                select(IngestionJob)
                .where(IngestionJob.document_version_id.in_(version_ids))
                .order_by(IngestionJob.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    jobs_by_version: dict[UUID, list[dict]] = {}
    for j in jobs:
        jobs_by_version.setdefault(j.document_version_id, []).append(_serialize_job(j))

    return {
        **_serialize_document(document, len(versions), 0),
        "versions": [
            {
                "document_version_id": str(v.document_version_id),
                "version_number": v.version_number,
                "object_key": v.object_key,
                "original_filename": v.original_filename,
                "checksum": v.checksum,
                "is_current": v.is_current,
                "previous_version_id": str(v.previous_version_id) if v.previous_version_id else None,
                "change_summary": v.change_summary,
                "status": v.status,
                "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
                "ingestion_jobs": jobs_by_version.get(v.document_version_id, []),
            }
            for v in versions
        ],
    }


def _serialize_job(job: IngestionJob) -> dict:
    return {
        "ingestion_job_id": str(job.ingestion_job_id),
        "document_version_id": str(job.document_version_id),
        "status": job.status.value if isinstance(job.status, IngestionStatus) else str(job.status),
        "failure_reason": job.failure_reason.value
        if job.failure_reason is not None
        else None,
        "error_message": job.error_message,
        "parser_version": job.parser_version,
        "chunking_strategy": job.chunking_strategy,
        "embedding_model": job.embedding_model,
        "embedding_version": job.embedding_version,
        "pipeline_version": job.pipeline_version,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Ingestion job status + provenance."""
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ingestion job not found")
    return _serialize_job(job)


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Retry a FAILED ingestion job in place (no re-upload)."""
    try:
        return await retry_ingestion_job(session, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    category: str | None = Query(None),
    top_k: int | None = Query(None, ge=1, le=50),
    generate: bool = Query(True, description="Generate a polished LLM answer when configured"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Knowledge Service hybrid retrieval over INDEXED versions only.

    When an LLM is configured (``LLM_ENABLED=true`` + ``LLM_API_KEY``) and
    ``generate=true``, the grounded context is turned into a polished,
    citation-aware answer by the generation model. Set ``generate=false`` for
    the raw retrieval result only.
    """
    service = KnowledgeService(
        HybridRetrievalRepository(session),
        _embedder(),
        reranker=_reranker(),
        llm=_llm() if generate else None,
    )
    result = await service.retrieve(
        q,
        category=_parse_category(category) if category else None,
        top_k=top_k,
    )
    answer = await service.generate_answer(q, result) if generate else None
    return {
        "query": q,
        "answer": answer,
        "grounded_context": result.grounded_context,
        "confidence": round(result.confidence, 4),
        "low_confidence": result.low_confidence,
        "citations": [
            {
                "chunk_id": str(c.chunk_id),
                "document_id": str(c.document_id),
                "document_version_id": str(c.document_version_id),
                "version_number": c.version_number,
                "document_title": c.document_title,
                "category": c.category,
                "page": c.page,
                "section_title": c.section_title,
            }
            for c in result.citations
        ],
        "chunks": [
            {
                "chunk_id": str(c.chunk_id),
                "document_title": c.document_title,
                "category": c.category,
                "section_title": c.section_title,
                "page": c.page,
                "text": c.text,
                "parent_context": c.parent_context,
                "retrieval_score": round(c.retrieval_score, 4),
                "reranker_score": round(c.reranker_score, 4) if c.reranker_score is not None else None,
                "confidence": round(c.confidence, 4),
                "provenance": {
                    "parser_version": c.provenance.parser_version if c.provenance else None,
                    "chunking_strategy": c.provenance.chunking_strategy if c.provenance else None,
                    "embedding_model": c.provenance.embedding_model if c.provenance else None,
                    "pipeline_version": c.provenance.pipeline_version if c.provenance else None,
                }
                if c.provenance
                else None,
            }
            for c in result.chunks
        ],
    }
