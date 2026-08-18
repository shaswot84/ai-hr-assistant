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


@pytest.mark.asyncio
async def test_repository_expands_leaf_to_parent_section(db_session):
    """fetch_parent_context returns the enclosing section, never the doc row."""
    from app.knowledge.repository import HybridRetrievalRepository

    doc = Document(
        title="Hybrid Work Policy",
        document_type="policy",
        category=DocumentCategory.POLICY,
        status="INDEXED",
    )
    db_session.add(doc)
    await db_session.flush()

    version = DocumentVersion(
        document_id=doc.document_id,
        version_number=1,
        object_key="documents/hybrid-work.pdf",
        original_filename="hybrid-work.pdf",
        mime_type="application/pdf",
        file_size=1000,
        checksum="leafctx",
        is_current=True,
        status="INDEXED",
    )
    db_session.add(version)
    await db_session.flush()

    job = IngestionJob(
        document_version_id=version.document_version_id,
        status=IngestionStatus.INDEXED,
        embedding_model="nomic-embed-text",
        chunking_strategy="hierarchical_small_to_big_v1",
    )
    db_session.add(job)
    await db_session.flush()

    # Document root row: whole-document context, never expanded into.
    doc_row = DocumentChunk(
        document_version_id=version.document_version_id,
        chunk_index=0,
        chunk_level="document",
        content="<whole document text>",
        processed_content="whole document text",
        embeddable=False,
    )
    db_session.add(doc_row)
    await db_session.flush()

    # Section row: the enclosing context a leaf expands into.
    section_row = DocumentChunk(
        document_version_id=version.document_version_id,
        chunk_index=1,
        chunk_level="section",
        parent_chunk_id=doc_row.chunk_id,
        content="Hybrid Work Procedure: sign the contract, receive equipment.",
        processed_content="hybrid work procedure sign contract receive equipment",
        section_title="Hybrid Work Procedure",
        embeddable=False,
    )
    db_session.add(section_row)
    await db_session.flush()

    leaf_row = DocumentChunk(
        document_version_id=version.document_version_id,
        chunk_index=2,
        chunk_level="leaf",
        parent_chunk_id=section_row.chunk_id,
        content="Sign the contract, then receive equipment.",
        processed_content="sign the contract then receive equipment",
        section_title="Hybrid Work Procedure",
        embeddable=True,
        embedding=make_embedding(1.0),
    )
    db_session.add(leaf_row)
    await db_session.flush()

    repo = HybridRetrievalRepository(db_session)

    # Leaf expands to its enclosing section text.
    expanded = await repo.fetch_parent_context([leaf_row.chunk_id])
    assert expanded == {leaf_row.chunk_id: section_row.content}

    # The section's own parent is the document root -> no expansion (the
    # whole-document text is never fed to the LLM).
    assert await repo.fetch_parent_context([section_row.chunk_id]) == {}
    assert await repo.fetch_parent_context([]) == {}


async def _indexed_doc(
    db_session,
    title: str,
    *,
    role_access: list[str],
    content: str,
    first: float = 1.0,
):
    """Insert one INDEXED document + current version + chunk + job."""
    from app.knowledge.models import (
        DocumentChunk,
        DocumentVersion,
        IngestionJob,
        IngestionStatus,
    )

    doc = Document(
        title=title,
        document_type="policy",
        category=DocumentCategory.POLICY,
        status="INDEXED",
        role_access=role_access,
    )
    db_session.add(doc)
    await db_session.flush()
    version = DocumentVersion(
        document_id=doc.document_id,
        version_number=1,
        object_key=f"documents/{title}.pdf",
        original_filename=f"{title}.pdf",
        mime_type="application/pdf",
        file_size=1000,
        checksum=title,
        is_current=True,
        status="INDEXED",
    )
    db_session.add(version)
    await db_session.flush()
    chunk = DocumentChunk(
        document_version_id=version.document_version_id,
        chunk_index=0,
        content=content,
        processed_content=content,
        embedding=make_embedding(first),
    )
    db_session.add(chunk)
    await db_session.flush()
    job = IngestionJob(
        document_version_id=version.document_version_id,
        status=IngestionStatus.INDEXED,
        embedding_model="nomic-embed-text",
        chunking_strategy="structure_aware_v1",
    )
    db_session.add(job)
    await db_session.flush()
    return doc, chunk


@pytest.mark.asyncio
async def test_repository_filters_by_access_roles(db_session):
    """Both legs only serve documents whose role_access contains the requester."""
    from app.knowledge.repository import HybridRetrievalRepository

    await _indexed_doc(
        db_session,
        "General Company Info",
        role_access=["VISITOR", "CANDIDATE", "EMPLOYEE", "HR_ADMIN"],
        content="Summit Technologies is a software company.",
        first=1.0,
    )
    await _indexed_doc(
        db_session,
        "Employee Leave Policy",
        role_access=["EMPLOYEE", "HR_ADMIN"],
        content="Employees accrue leave per month.",
        first=2.0,
    )
    await _indexed_doc(
        db_session,
        "Confidential Compensation",
        role_access=["HR_ADMIN"],
        content="Compensation bands are confidential.",
        first=3.0,
    )
    repo = HybridRetrievalRepository(db_session)

    bm25 = await repo.bm25_search("company leave compensation", limit=10, access_roles=["VISITOR"])
    titles = {h.document_title for h in bm25}
    assert titles == {"General Company Info"}

    vector = await repo.vector_search(make_embedding(1.0), limit=10, access_roles=["EMPLOYEE"])
    vector_titles = {h.document_title for h in vector}
    assert vector_titles == {"General Company Info", "Employee Leave Policy"}

    unrestricted = await repo.vector_search(make_embedding(1.0), limit=10)
    assert {h.document_title for h in unrestricted} == {
        "General Company Info",
        "Employee Leave Policy",
        "Confidential Compensation",
    }


@pytest.mark.asyncio
async def test_repository_restricted_matches_probe(db_session):
    """restricted_matches returns only excluded docs, identity metadata only."""
    from app.knowledge.repository import HybridRetrievalRepository

    await _indexed_doc(
        db_session,
        "General Company Info",
        role_access=["VISITOR", "CANDIDATE", "EMPLOYEE", "HR_ADMIN"],
        content="Summit Technologies is a software company.",
        first=1.0,
    )
    await _indexed_doc(
        db_session,
        "Confidential Compensation",
        role_access=["HR_ADMIN"],
        content="Compensation bands are confidential.",
        first=3.0,
    )
    repo = HybridRetrievalRepository(db_session)

    restricted = await repo.restricted_matches("company compensation", access_roles=["VISITOR"])

    assert [d.title for d in restricted] == ["Confidential Compensation"]
    assert restricted[0].allowed_roles == ["HR_ADMIN"]
    # Never content: RestrictedDocument has no content field by construction.
    assert not hasattr(restricted[0], "content")


@pytest.mark.asyncio
async def test_repository_has_indexed_documents(db_session):
    """has_indexed_documents reflects the presence of INDEXED, non-deleted docs."""
    from app.knowledge.repository import HybridRetrievalRepository

    repo = HybridRetrievalRepository(db_session)
    assert await repo.has_indexed_documents() is False

    await _indexed_doc(
        db_session,
        "General Company Info",
        role_access=["VISITOR", "CANDIDATE", "EMPLOYEE", "HR_ADMIN"],
        content="Summit Technologies is a software company.",
        first=1.0,
    )
    assert await repo.has_indexed_documents() is True

    # A pending-only document does not make the knowledge base non-empty.
    await _indexed_doc(db_session, "Pending Doc", role_access=["HR_ADMIN"], content="x.", first=2.0)
    pending = Document(
        title="Pending Only",
        document_type="policy",
        category=DocumentCategory.POLICY,
        status="PENDING",
    )
    db_session.add(pending)
    await db_session.flush()
    version = DocumentVersion(
        document_id=pending.document_id,
        version_number=1,
        object_key="documents/pending-only.pdf",
        original_filename="pending-only.pdf",
        mime_type="application/pdf",
        file_size=1,
        checksum="pending-only",
        is_current=True,
        status="PENDING",
    )
    db_session.add(version)
    await db_session.flush()
    job = IngestionJob(
        document_version_id=version.document_version_id,
        status=IngestionStatus.PENDING,
    )
    db_session.add(job)
    await db_session.flush()

    assert await repo.has_indexed_documents() is True
