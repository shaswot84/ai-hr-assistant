"""The chat pipeline over the real RAG stack (pgvector).

Gated on ``TEST_DATABASE_URL`` like the repository/ingestion integration
tests (skipped otherwise; the CI workflow provisions pgvector and sets it).

Ingests the SHIPPED sample corpus (``backend/sample_docs`` — the same
documents ``scripts/seed_knowledge.py`` uploads) through the real ingestion
pipeline, then drives the real supervisor graph with a real KnowledgeService
and asserts the knowledge node retrieves and grounds its answer from the
actually-indexed policy documents. This is the end-to-end proof for the
routing fixes: a leave-policy question must come back as a grounded,
citation-bearing answer, not a refusal, when the corpus is seeded.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.integrations.object_store import ObjectStoreError
from app.jobs.ingestion_worker import claim_next_jobs, process_job
from app.knowledge.ingestion.orchestrator import register_document
from app.knowledge.models import DocumentCategory

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SAMPLE_DOCS = Path(__file__).resolve().parents[3] / "sample_docs"


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


class KeywordEmbedder:
    """Deterministic bag-of-words embedding: texts sharing keywords get high
    cosine similarity, so the semantic leg agrees with the BM25 leg and the
    confidence gate passes for genuinely relevant queries (a hash-of-text
    embedder would give orthogonal vectors and a guaranteed refusal)."""

    model = "fake/nomic-embed-text"
    version = "1.0"
    DIM = 768

    async def embed(self, texts: list[str], *, prefix: str = "") -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.DIM
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                idx = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.DIM
                vec[idx] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


class RouteAndRewriteLLM:
    """Graph LLM: routing -> 'knowledge'; query rewrite -> a self-contained
    query that actually matches the seeded corpus."""

    model = "fake"

    async def complete(self, system: str, user: str) -> str:
        if "rewrite an HR question" in system:
            return "how many days of paid annual leave do employees get per year"
        return "knowledge"


@pytest.fixture
async def db_session():
    """Fresh schema on an ephemeral test DB; skip when no URL is provided."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set; skipping pgvector chat pipeline test")
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


async def _ingest_corpus(session, store, embedder) -> list[str]:
    """Register + index every sample doc through the real pipeline."""
    titles = []
    for path in sorted(SAMPLE_DOCS.glob("*.md")):
        uploaded = await register_document(
            session,
            store,
            filename=path.name,
            data=path.read_bytes(),
            category=DocumentCategory.POLICY,
        )
        assert uploaded["status"] == "PENDING"
        claimed = await claim_next_jobs(session, limit=10)
        assert any(str(j.ingestion_job_id) == uploaded["ingestion_job_id"] for j in claimed)
        summary = await process_job(session, uploaded["ingestion_job_id"], store, embedder)
        assert summary["status"] == "INDEXED"
        titles.append(path.name)
    return titles


@pytest.mark.asyncio
async def test_leave_policy_question_retrieves_grounded_answer(db_session):
    """The seeded corpus is ingested; a leave-policy question runs the real
    supervisor graph and comes back as a grounded, citation-bearing answer —
    the exact path the routing fixes depend on."""
    from app.agents.supervisor.graph import build_supervisor_graph
    from app.config.settings import RetrievalSettings
    from app.knowledge.repository import HybridRetrievalRepository
    from app.knowledge.reranker import PassThroughReranker
    from app.knowledge.service import KnowledgeService

    store = MemoryObjectStore()
    embedder = KeywordEmbedder()
    titles = await _ingest_corpus(db_session, store, embedder)
    assert "annual_leave_policy.md" in titles
    assert len(titles) == len(list(SAMPLE_DOCS.glob("*.md")))

    # Real retrieval over pgvector; a lowered confidence threshold keeps the
    # assertion on pipeline wiring, not on the synthetic embedder's
    # (arbitrary) cosine magnitudes. Generation is skipped (llm=None) so the
    # served answer is the grounded context itself.
    service = KnowledgeService(
        HybridRetrievalRepository(db_session),
        embedder,
        reranker=PassThroughReranker(),
        llm=None,
        settings=RetrievalSettings(confidence_threshold=0.2),
    )
    graph = build_supervisor_graph(llm=RouteAndRewriteLLM(), knowledge_service=service)

    state = await graph.ainvoke(
        {"messages": [], "current_query": "how many days of annual leave do i get per year"}
    )

    assert state["agent"] == "knowledge"
    assert state["knowledge_result"] is not None
    assert state["knowledge_result"].low_confidence is False
    assert state["confidence"] > 0
    assert state["citations"], "retrieval must return a citation from the ingested corpus"
    assert "annual_leave_policy" in {c.document_title for c in state["citations"]}
    assert "20" in state["answer"], "the grounded answer must carry the policy entitlement"


@pytest.mark.asyncio
async def test_question_without_evidence_gets_honest_refusal(db_session):
    """A question with nothing in the corpus refuses honestly instead of
    fabricating — the low-confidence gate holds through the real pipeline."""
    from app.agents.supervisor.graph import build_supervisor_graph
    from app.knowledge.repository import HybridRetrievalRepository
    from app.knowledge.reranker import PassThroughReranker
    from app.knowledge.service import KnowledgeService

    store = MemoryObjectStore()
    embedder = KeywordEmbedder()
    await _ingest_corpus(db_session, store, embedder)

    service = KnowledgeService(
        HybridRetrievalRepository(db_session),
        embedder,
        reranker=PassThroughReranker(),
        llm=None,
    )
    graph = build_supervisor_graph(llm=RouteAndRewriteLLM(), knowledge_service=service)

    state = await graph.ainvoke(
        {"messages": [], "current_query": "what is the procurement approval workflow"}
    )

    assert state["agent"] == "knowledge"
    assert state["knowledge_result"].low_confidence is True or not state["citations"]
    assert "couldn't find enough evidence" in state["answer"]
    assert state["citations"] == []
