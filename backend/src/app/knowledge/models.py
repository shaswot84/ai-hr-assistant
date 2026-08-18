"""SQLAlchemy models for the knowledge/retrieval domain.

Tables: ``document`` → ``document_version`` → ``document_chunk``, plus
``ingestion_job`` tracking the pipeline that produced each version.

The agent and Knowledge Service never write here directly — the ingestion
pipeline owns these rows and marks a version INDEXED only when it is ready
to be served (see ``HybridRetrievalRepository``).
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.settings import get_settings
from app.db.base import Base
from app.knowledge.access import ALL_ACCESS_ROLES

# Read once so the embedding column width matches the configured model.
_EMBEDDING_DIM = get_settings().embedding.dimension


class DocumentCategory(enum.Enum):
    """Coarse HR document taxonomy used for retrieval metadata filters."""

    POLICY = "POLICY"
    PROCEDURE = "PROCEDURE"
    GUIDELINE = "GUIDELINE"
    FORM = "FORM"
    TEMPLATE = "TEMPLATE"
    TRAINING_MATERIAL = "TRAINING_MATERIAL"
    OTHER = "OTHER"


class IngestionStatus(enum.Enum):
    """Lifecycle of an ingestion job; only ``INDEXED`` rows are served."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class FailureReason(enum.Enum):
    """Why an ingestion job failed (stored for observability)."""

    PARSING_ERROR = "PARSING_ERROR"
    CHUNKING_ERROR = "CHUNKING_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Document(Base):
    """Top-level knowledge document (e.g. "Leave Policy")."""

    __tablename__ = "document"

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, name="document_category"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Exact allowlist of roles that may retrieve this document (set by the
    # uploader at submit time; HR_ADMIN is always present).
    role_access: Mapped[list[str]] = mapped_column(
        JSON().with_variant(postgresql.JSONB(), "postgresql"),
        default=list(ALL_ACCESS_ROLES),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # References application_user.user_id; FK added once identity tables exist.
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    """An immutable snapshot of a document at a point in time.

    The authoritative bytes live in MinIO (``object_key``); only the current
    version is served by default.
    """

    __tablename__ = "document_version"

    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.document_id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_version.document_version_id"), nullable=True
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # References application_user.user_id; FK added once identity tables exist.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Dedup backstop: at most one INDEXED version per content checksum.
        # The same bytes re-uploaded (any document) are skipped, not re-indexed.
        Index(
            "uq_version_checksum_indexed",
            "checksum",
            unique=True,
            postgresql_where=text("status = 'INDEXED'"),
        ),
    )


class DocumentChunk(Base):
    """A node in the hierarchical chunk tree of a version.

    Small-to-big tree: one ``document`` row -> ``section`` rows (per heading)
    -> ``leaf`` rows (budget-split, the only embedded + BM25-indexed rows).
    Context (``document``/``section``) rows carry ``embedding = NULL`` and
    ``embeddable = 0``; retrieval expands a matched leaf to its ancestors via
    ``parent_chunk_id`` / ``ancestors``.
    """

    __tablename__ = "document_chunk"

    chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_version.document_version_id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Tree node kind: ``document`` | ``section`` | ``leaf``.
    chunk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="leaf")
    # Parent node's chunk_id (NULL at the document root).
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunk.chunk_id"), nullable=True
    )
    # Ordered parent chunk_id chain, root-most last (JSON array of UUIDs).
    ancestors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 1 for leaf rows (embedded + FTS-indexed); 0 for context rows.
    embeddable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Raw extracted text as written in the source document.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Normalized text actually used for FTS indexing and embedding.
    processed_content: Mapped[str] = mapped_column(Text, nullable=False)
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlap_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overlap_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Full heading path, e.g. "Leave Policy > Annual Leave".
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pgvector column: float vector sized to the embedding model's dimension.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")

    __table_args__ = (
        # No duplicate or re-ordered chunks within a version.
        UniqueConstraint("document_version_id", "chunk_index"),
        # Fast context expansion: parent of a matched leaf.
        Index("ix_document_chunk_parent", "document_version_id", "parent_chunk_id"),
    )


class IngestionJob(Base):
    """Tracks the ingestion pipeline run that produced a version's chunks.

    Provenance fields (parser/chunking/embedding model) support explainability
    and rebuilding derived indexes without touching authoritative documents.
    """

    __tablename__ = "ingestion_job"

    ingestion_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_version.document_version_id"), nullable=False, index=True
    )
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="ingestion_status"), nullable=False
    )
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        Enum(FailureReason, name="failure_reason"), nullable=True
    )
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chunking_strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="ingestion_jobs")
