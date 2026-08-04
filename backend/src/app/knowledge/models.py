import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config.settings import get_settings
from app.db.base import Base

_EMBEDDING_DIM = get_settings().embedding.dimension


class DocumentCategory(enum.Enum):
    POLICY = "POLICY"
    PROCEDURE = "PROCEDURE"
    GUIDELINE = "GUIDELINE"
    FORM = "FORM"
    TEMPLATE = "TEMPLATE"
    TRAINING_MATERIAL = "TRAINING_MATERIAL"
    OTHER = "OTHER"


class IngestionStatus(enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class FailureReason(enum.Enum):
    PARSING_ERROR = "PARSING_ERROR"
    CHUNKING_ERROR = "CHUNKING_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Document(Base):
    __tablename__ = "document"

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, name="document_category"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
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


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_version.document_version_id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    processed_content: Mapped[str] = mapped_column(Text, nullable=False)
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlap_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overlap_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")

    __table_args__ = (
        # No duplicate or re-ordered chunks within a version.
        UniqueConstraint("document_version_id", "chunk_index"),
    )


class IngestionJob(Base):
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
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="ingestion_jobs")
