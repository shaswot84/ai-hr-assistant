"""End-to-end ingestion flow against a real pgvector database.

Gated on ``TEST_DATABASE_URL`` (skipped otherwise, like the repository
integration tests). Exercises the full write side:

    upload/registry (orchestrator) -> claim (worker) -> process
      (engine -> embed -> persist) -> INDEXED
      -> hybrid retrieval serves only INDEXED + current versions

plus checksum dedup (SKIPPED_DUPLICATE), version-bump / is_current /
previous_version_id, failure classification (FAILED + failure_reason),
and retry-in-place.
"""

import hashlib
import math
import os

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.integrations.object_store import ObjectStoreError
from app.jobs.ingestion_worker import claim_next_jobs, process_job, retry_job
from app.knowledge.ingestion.orchestrator import (
    clear_all_documents,
    register_document,
    soft_delete_document,
)
from app.knowledge.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentVersion,
    FailureReason,
    IngestionJob,
    IngestionStatus,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

FAQ_MD = """# Annual Leave

## Entitlement

Employees receive 20 days of paid annual leave per year.

## Carryover

Unused leave may carry over up to 5 days into the next year.
"""

FAQ_MD_V2 = """# Annual Leave

## Entitlement

Employees receive 25 days of paid annual leave per year.

## Carryover

Unused leave may carry over up to 10 days into the next year.
"""


class MemoryObjectStore:
    """In-memory ObjectStore stand-in (no MinIO needed for these tests)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self.objects[key] = data

    async def get_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectStoreError(f"s3 get '{key}': not found")
        return self.objects[key]

    async def delete_bytes(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeEmbedder:
    """Deterministic 768-dim L2-normalized embeddings (no network)."""

    model = "fake/nomic-embed-text"
    version = "1.0"

    async def embed(self, texts: list[str], *, prefix: str = "") -> list[list[float]]:
        assert prefix == "search_document: "
        out = []
        for text in texts:
            h = hashlib.sha256(f"seed:{prefix}{text}".encode()).digest()
            vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(768)]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


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


def _leaf_texts(session) -> list[str]:
    """Embeddable (leaf) chunk contents of the current, INDEXED version."""
    rows = (
        session.execute(
            select(DocumentChunk.content)
            .join(DocumentVersion, DocumentVersion.document_version_id == DocumentChunk.document_version_id)
            .where(DocumentVersion.is_current.is_(True), DocumentChunk.embeddable.is_(True))
            .order_by(DocumentChunk.chunk_index)
        )
        .scalars()
        .all()
    )
    return list(rows)


@pytest.mark.asyncio
async def test_end_to_end_register_process_index_search(db_session):
    store = MemoryObjectStore()
    embedder = FakeEmbedder()
    data = FAQ_MD.encode()

    uploaded = await register_document(
        db_session, store,
        filename="annual_leave.md", data=data,
        category=DocumentCategory.POLICY,
    )
    assert uploaded["status"] == "PENDING"
    assert uploaded["object_key"] in store.objects
    assert store.objects[uploaded["object_key"]] == data

    # Job is PENDING and not yet servable.
    job = await db_session.get(IngestionJob, uploaded["ingestion_job_id"])
    assert job.status == IngestionStatus.PENDING

    claimed = await claim_next_jobs(db_session, limit=10)
    assert [str(j.ingestion_job_id) for j in claimed] == [uploaded["ingestion_job_id"]]

    summary = await process_job(db_session, job.ingestion_job_id, store, embedder)
    assert summary["status"] == "INDEXED"
    assert summary["embeddable_chunks"] >= 1

    # Lifecycle: everything INDEXED, one current version.
    job = await db_session.get(IngestionJob, uploaded["ingestion_job_id"])
    assert job.status == IngestionStatus.INDEXED
    assert job.pipeline_version == "structure_aware_v3"
    assert job.embedding_model == "fake/nomic-embed-text"
    version = await db_session.get(DocumentVersion, uploaded["document_version_id"])
    assert version.status == "INDEXED" and version.is_current is True
    document = await db_session.get(Document, uploaded["document_id"])
    assert document.status == "INDEXED"
    assert document.role_access == ["HR_ADMIN", "EMPLOYEE", "CANDIDATE", "VISITOR"]

    # Chunk tree: leaf rows embedded, context rows NULL embeddings.
    chunks = (
        (await db_session.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_version_id == uploaded["document_version_id"]
            )
        ))
        .scalars()
        .all()
    )
    assert len(chunks) >= 3  # document + section(s) + leaf(s)
    leaves = [c for c in chunks if c.embeddable]
    assert leaves and all(c.embedding is not None for c in leaves)
    assert all(c.embedding is None for c in chunks if not c.embeddable)
    # ancestors resolve to real chunk_ids and climb to the root.
    root = next(c for c in chunks if c.chunk_level == "document")
    leaf = leaves[0]
    assert leaf.parent_chunk_id is not None
    if leaf.ancestors:
        assert leaf.ancestors[-1] == str(root.chunk_id)
    assert leaf.section_path  # e.g. "Annual Leave > Entitlement"

    # Read side serves it (BM25 leg matches the indexed content).
    from app.knowledge.repository import HybridRetrievalRepository

    repo = HybridRetrievalRepository(db_session)
    hits = await repo.bm25_search("paid annual leave", limit=10)
    assert hits, "INDEXED current version must be retrievable"
    assert any("20 days" in h.content for h in hits)

    # Scores are computed at query time, never persisted.
    cols = {
        row["name"]
        for row in (
            await db_session.execute(sa.text(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_name = 'document_chunk'"
            ))
        ).mappings()
    }
    assert not {"cosine", "bm25", "rrf", "confidence"} & cols


@pytest.mark.asyncio
async def test_duplicate_checksum_skipped(db_session):
    store = MemoryObjectStore()
    embedder = FakeEmbedder()
    data = FAQ_MD.encode()

    first = await register_document(db_session, store, filename="annual_leave.md", data=data,
                                    category=DocumentCategory.POLICY)
    await process_job(db_session, first["ingestion_job_id"], store, embedder)

    # Same bytes under a different filename -> SKIPPED_DUPLICATE, no new rows.
    dup = await register_document(db_session, store, filename="copy.md", data=data,
                                  category=DocumentCategory.POLICY)
    assert dup["status"] == "SKIPPED_DUPLICATE"
    assert dup["document_version_id"] == first["document_version_id"]
    n_versions = (await db_session.execute(
        select(sa.func.count()).select_from(DocumentVersion)
    )).scalar()
    assert n_versions == 1
    n_jobs = (await db_session.execute(
        select(sa.func.count()).select_from(IngestionJob)
    )).scalar()
    assert n_jobs == 1


@pytest.mark.asyncio
async def test_version_bump_supersedes_old(db_session):
    store = MemoryObjectStore()
    embedder = FakeEmbedder()

    v1 = await register_document(db_session, store, filename="annual_leave.md",
                                 data=FAQ_MD.encode(), category=DocumentCategory.POLICY)
    await process_job(db_session, v1["ingestion_job_id"], store, embedder)

    v2 = await register_document(db_session, store, filename="annual_leave.md",
                                 data=FAQ_MD_V2.encode(), category=DocumentCategory.POLICY)
    assert v2["status"] == "PENDING" and v2["version_number"] == 2
    await process_job(db_session, v2["ingestion_job_id"], store, embedder)

    version1 = await db_session.get(DocumentVersion, v1["document_version_id"])
    version2 = await db_session.get(DocumentVersion, v2["document_version_id"])
    assert version1.is_current is False
    assert version2.is_current is True
    assert version2.previous_version_id == version1.document_version_id
    assert version2.change_summary  # version_diff stats recorded as JSON

    # Old version's chunks still exist (immutable snapshot) but are not served.
    n_chunks = (await db_session.execute(
        select(sa.func.count()).select_from(DocumentChunk)
    )).scalar()
    assert n_chunks >= 2

    from app.knowledge.repository import HybridRetrievalRepository

    repo = HybridRetrievalRepository(db_session)
    hits = await repo.bm25_search("annual leave", limit=10)
    assert hits and all("25 days" in h.content for h in hits)
    assert all("20 days" not in h.content for h in hits)


@pytest.mark.asyncio
async def test_failure_classification_and_retry(db_session):
    store = MemoryObjectStore()
    embedder = FakeEmbedder()

    # 1. Unparseable bytes -> PARSING_ERROR.
    bad = await register_document(db_session, store, filename="broken.bin",
                                  data=b"\x00\x01\x02 not a document",
                                  category=DocumentCategory.OTHER)
    failed = await process_job(db_session, bad["ingestion_job_id"], store, embedder)
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == "PARSING_ERROR"
    job = await db_session.get(IngestionJob, bad["ingestion_job_id"])
    assert job.status == IngestionStatus.FAILED
    assert job.failure_reason == FailureReason.PARSING_ERROR
    assert "UNSUPPORTED_FORMAT" in (job.error_message or "")
    version = await db_session.get(DocumentVersion, bad["document_version_id"])
    assert version.status == "FAILED" and version.is_current is False

    # 2. STORAGE_ERROR when MinIO is unreachable.
    gone = await register_document(db_session, store, filename="ok.md",
                                   data=FAQ_MD.encode(), category=DocumentCategory.POLICY)
    store.objects.pop(gone["object_key"])
    failed2 = await process_job(db_session, gone["ingestion_job_id"], store, embedder)
    assert failed2["failure_reason"] == "STORAGE_ERROR"

    # 3. Retry-in-place: put the source back, retry, expect INDEXED on the
    #    same version row (no re-upload, no new version).
    store.objects[gone["object_key"]] = FAQ_MD.encode()
    retried = await retry_job(db_session, gone["ingestion_job_id"])
    assert retried["status"] == "PENDING"
    summary = await process_job(db_session, gone["ingestion_job_id"], store, embedder)
    assert summary["status"] == "INDEXED"
    version = await db_session.get(DocumentVersion, gone["document_version_id"])
    assert version.status == "INDEXED" and version.is_current is True

    # 4. Failed PENDING retry is rejected (only FAILED jobs may retry).
    with pytest.raises(ValueError):
        await retry_job(db_session, gone["ingestion_job_id"])


@pytest.mark.asyncio
async def test_soft_delete_hides_from_search_and_removes_object(db_session):
    store = MemoryObjectStore()
    embedder = FakeEmbedder()
    data = FAQ_MD.encode()

    uploaded = await register_document(
        db_session, store, filename="annual_leave.md", data=data,
        category=DocumentCategory.POLICY,
    )
    await process_job(db_session, uploaded["ingestion_job_id"], store, embedder)
    assert uploaded["object_key"] in store.objects

    from app.knowledge.repository import HybridRetrievalRepository

    repo = HybridRetrievalRepository(db_session)
    assert await repo.bm25_search("paid annual leave", limit=10)

    summary = await soft_delete_document(db_session, store, uploaded["document_id"])
    assert summary["status"] == "DELETED"
    assert summary["removed"] == 1
    assert uploaded["object_key"] not in store.objects

    # Tombstoned: registry listing hides it, detail 404s, retrieval serves it.
    doc = await db_session.get(Document, uploaded["document_id"])
    assert doc.deleted_at is not None
    assert not await repo.bm25_search("paid annual leave", limit=10)


@pytest.mark.asyncio
async def test_clear_all_removes_documents_chunks_jobs_and_objects(db_session):
    store = MemoryObjectStore()
    embedder = FakeEmbedder()

    uploaded = await register_document(
        db_session, store, filename="annual_leave.md", data=FAQ_MD.encode(),
        category=DocumentCategory.POLICY,
    )
    await process_job(db_session, uploaded["ingestion_job_id"], store, embedder)

    summary = await clear_all_documents(db_session, store)
    assert summary["deleted_documents"] == 1
    assert summary["removed_objects"] == 1
    assert uploaded["object_key"] not in store.objects

    from sqlalchemy import func, select

    counts = {
        table: (await db_session.execute(select(func.count()).select_from(model))).scalar()
        for table, model in [
            ("document", Document),
            ("document_version", DocumentVersion),
            ("document_chunk", DocumentChunk),
            ("ingestion_job", IngestionJob),
        ]
    }
    assert all(n == 0 for n in counts.values()), counts

    # Checksum dedup backstop is freed: identical bytes re-index cleanly.
    again = await register_document(
        db_session, store, filename="annual_leave.md", data=FAQ_MD.encode(),
        category=DocumentCategory.POLICY,
    )
    assert again["status"] == "PENDING"
    summary2 = await process_job(db_session, again["ingestion_job_id"], store, embedder)
    assert summary2["status"] == "INDEXED"
