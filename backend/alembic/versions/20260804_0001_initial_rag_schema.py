"""Initial RAG / knowledge schema

Revision ID: 20260804_0001
Revises:
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from app.config.settings import get_settings

# revision identifiers, used by Alembic.
revision: str = "20260804_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    document_category = sa.Enum(
        "POLICY", "PROCEDURE", "GUIDELINE", "FORM",
        "TEMPLATE", "TRAINING_MATERIAL", "OTHER",
        name="document_category",
    )
    ingestion_status = sa.Enum(
        "PENDING", "PROCESSING", "INDEXED", "FAILED",
        name="ingestion_status",
    )
    failure_reason = sa.Enum(
        "PARSING_ERROR", "CHUNKING_ERROR", "EMBEDDING_ERROR",
        "STORAGE_ERROR", "TIMEOUT", "UNKNOWN",
        name="failure_reason",
    )

    op.create_table(
        "document",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("category", document_category, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index("ix_document_deleted_at", "document", ["deleted_at"])

    op.create_table(
        "document_version",
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.document_id"]),
        sa.ForeignKeyConstraint(["previous_version_id"], ["document_version.document_version_id"]),
        sa.PrimaryKeyConstraint("document_version_id"),
        sa.UniqueConstraint("document_id", "version_number"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_document_version_document_id", "document_version", ["document_id"])
    op.create_index("ix_document_version_checksum", "document_version", ["checksum"])

    op.create_table(
        "document_chunk",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("processed_content", sa.Text(), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=True),
        sa.Column("overlap_start", sa.Integer(), nullable=True),
        sa.Column("overlap_end", sa.Integer(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(length=500), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(get_settings().embedding.dimension), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_version.document_version_id"]),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint("document_version_id", "chunk_index"),
    )
    op.create_index("ix_document_chunk_document_version_id", "document_chunk", ["document_version_id"])
    # Semantic index (pgvector) and lexical index (BM25) used by hybrid retrieval.
    op.execute(
        "CREATE INDEX ix_document_chunk_embedding_hnsw "
        "ON document_chunk USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunk_fts ON document_chunk "
        "USING GIN (to_tsvector('english', processed_content))"
    )

    op.create_table(
        "ingestion_job",
        sa.Column("ingestion_job_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", ingestion_status, nullable=False),
        sa.Column("failure_reason", failure_reason, nullable=True),
        sa.Column("parser_version", sa.String(length=100), nullable=True),
        sa.Column("chunking_strategy", sa.String(length=100), nullable=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
        sa.Column("embedding_version", sa.String(length=100), nullable=True),
        sa.Column("pipeline_version", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_version.document_version_id"]),
        sa.PrimaryKeyConstraint("ingestion_job_id"),
    )
    op.create_index("ix_ingestion_job_document_version_id", "ingestion_job", ["document_version_id"])


def downgrade() -> None:
    op.drop_table("ingestion_job")
    op.drop_index("ix_document_chunk_fts", table_name="document_chunk")
    op.drop_index("ix_document_chunk_embedding_hnsw", table_name="document_chunk")
    op.drop_table("document_chunk")
    op.drop_table("document_version")
    op.drop_table("document")

    op.execute("DROP TYPE IF EXISTS failure_reason")
    op.execute("DROP TYPE IF EXISTS ingestion_status")
    op.execute("DROP TYPE IF EXISTS document_category")
    op.execute("DROP EXTENSION IF EXISTS vector")
