"""Integration tests for the hybrid retrieval repository.

These run against a real pgvector database and are gated on
``TEST_DATABASE_URL``; without it they skip. They verify the core contract:
only chunks belonging to INDEXED, current versions are served.
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.knowledge.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    IngestionStatus,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def make_embedding(first: float = 1.0) -> list[float]:
    """Build a valid 768-dim embedding vector for tests."""
    vec = [0.0] * 768
    vec[0] = first
    return vec


@pytest.fixture
async def db_session():
    """Fresh schema on an ephemeral test DB; skip when no URL is provided."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set; skipping pgvector integration test")
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_serves_only_indexed_current_chunks(db_session):
    """INDEXED + current chunks are served; stale (non-current) are not."""
    from app.knowledge.repository import HybridRetrievalRepository

    doc = Document(
        title="Leave Policy",
        document_type="policy",
        category=DocumentCategory.POLICY,
        description="Annual leave rules",
        status="INDEXED",
    )
    db_session.add(doc)
    await db_session.flush()

    # Current (v1) and stale (v2, is_current=False) versions of the same doc.
    current_version = DocumentVersion(
        document_id=doc.document_id,
        version_number=1,
        object_key="documents/leave-policy-v1.pdf",
        original_filename="leave-policy.pdf",
        mime_type="application/pdf",
        file_size=1000,
        checksum="abc123",
        is_current=True,
        status="INDEXED",
    )
    stale_version = DocumentVersion(
        document_id=doc.document_id,
        version_number=2,
        object_key="documents/leave-policy-v2.pdf",
        original_filename="leave-policy-v2.pdf",
        mime_type="application/pdf",
        file_size=1000,
        checksum="def456",
        is_current=False,
        status="INDEXED",
    )
    db_session.add_all([current_version, stale_version])
    await db_session.flush()

    current_chunk = DocumentChunk(
        document_version_id=current_version.document_version_id,
        chunk_index=0,
        content="Annual leave accrues at 1.5 days per month.",
        processed_content="annual leave accrues at 1.5 days per month",
        page_number=2,
        section_title="Annual Leave",
        embedding=make_embedding(1.0),
    )
    stale_chunk = DocumentChunk(
        document_version_id=stale_version.document_version_id,
        chunk_index=0,
        content="This old version says two days.",
        processed_content="this old version says two days",
        embedding=make_embedding(1.0),
    )
    db_session.add_all([current_chunk, stale_chunk])
    await db_session.flush()

    indexed_job = IngestionJob(
        document_version_id=current_version.document_version_id,
        status=IngestionStatus.INDEXED,
        embedding_model="nomic-embed-text",
        chunking_strategy="structure_aware_v1",
    )
    stale_job = IngestionJob(
        document_version_id=stale_version.document_version_id,
        status=IngestionStatus.INDEXED,
        embedding_model="nomic-embed-text",
        chunking_strategy="structure_aware_v1",
    )
    db_session.add_all([indexed_job, stale_job])
    await db_session.flush()

    repo = HybridRetrievalRepository(db_session)

    # BM25 leg: only the current version's chunk matches.
    bm25 = await repo.bm25_search("annual leave accrues", limit=10)
    assert [h.content for h in bm25] == [current_chunk.content]

    # Vector leg: current chunk first; metadata (category) comes through.
    vector = await repo.vector_search(make_embedding(1.0), limit=10)
    assert vector[0].chunk_id == current_chunk.chunk_id
    assert vector[0].category == "POLICY"

    # current_only=False lets stale versions through.
    with_all_versions = await repo.vector_search(make_embedding(1.0), limit=10, current_only=False)
    ids = {h.chunk_id for h in with_all_versions}
    assert current_chunk.chunk_id in ids
    assert stale_chunk.chunk_id in ids


@pytest.mark.asyncio
async def test_repository_excludes_non_indexed(db_session):
    """Non-INDEXED versions/jobs are never returned by either leg."""
    from app.knowledge.repository import HybridRetrievalRepository

    doc = Document(
        title="Pending Doc",
        document_type="policy",
        category=DocumentCategory.POLICY,
        status="PROCESSING",
    )
    db_session.add(doc)
    await db_session.flush()

    version = DocumentVersion(
        document_id=doc.document_id,
        version_number=1,
        object_key="documents/pending.pdf",
        original_filename="pending.pdf",
        mime_type="application/pdf",
        file_size=1,
        checksum="zzz",
        is_current=True,
        status="PROCESSING",
    )
    db_session.add(version)
    await db_session.flush()

    chunk = DocumentChunk(
        document_version_id=version.document_version_id,
        chunk_index=0,
        content="Half ingested content.",
        processed_content="half ingested content",
        embedding=make_embedding(1.0),
    )
    db_session.add(chunk)
    await db_session.flush()

    job = IngestionJob(
        document_version_id=version.document_version_id,
        status=IngestionStatus.PROCESSING,
    )
    db_session.add(job)
    await db_session.flush()

    repo = HybridRetrievalRepository(db_session)

    bm25 = await repo.bm25_search("half ingested", limit=10)
    vector = await repo.vector_search(make_embedding(1.0), limit=10)

    assert bm25 == []
    assert vector == []
