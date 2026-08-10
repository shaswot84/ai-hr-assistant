"""Unit tests for the KnowledgeService orchestrator using fakes."""

import uuid

import pytest

from app.config.settings import RetrievalSettings
from app.knowledge.models import DocumentCategory
from app.knowledge.repository import RetrievalHit
from app.knowledge.reranker import PassThroughReranker
from app.knowledge.service import KnowledgeService
from app.model_gateway.interfaces import LLM, Embedder, Reranker


def make_hit(chunk_id: str, content: str, category: str = "POLICY") -> RetrievalHit:
    """Build a RetrievalHit with a deterministic chunk id."""
    return RetrievalHit(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, chunk_id),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        version_number=1,
        document_title="Leave Policy",
        category=category,
        page=2,
        section_title="Annual Leave",
        content=content,
        score=0.9,
    )


class FakeRepository:
    """Stands in for HybridRetrievalRepository; records filter kwargs."""

    def __init__(self, bm25_hits: list[RetrievalHit], vector_hits: list[RetrievalHit]) -> None:
        self._bm25_hits = bm25_hits
        self._vector_hits = vector_hits
        self.last_kwargs: dict = {}

    async def bm25_search(self, query, limit, **kwargs):
        self.last_kwargs["bm25"] = kwargs
        return self._bm25_hits

    async def vector_search(self, query_embedding, limit, **kwargs):
        self.last_kwargs["vector"] = kwargs
        return self._vector_hits

    async def fetch_parent_context(self, chunk_ids):
        return {}


class FakeRepositoryWithParents(FakeRepository):
    """Fake repository that returns parent section text for known leaves."""

    def __init__(self, bm25_hits, vector_hits, parent_contexts=None):
        super().__init__(bm25_hits, vector_hits)
        self._parent_contexts = parent_contexts or {}

    async def fetch_parent_context(self, chunk_ids):
        return {cid: text for cid, text in self._parent_contexts.items() if cid in chunk_ids}


class FakeEmbedder(Embedder):
    """Deterministic embedder returning a constant vector."""

    model = "fake"
    version = "1"
    dimension = 4

    async def embed(self, texts, *, prefix=""):
        # The service must use the nomic query prefix so query embeddings are
        # in the same space as ingestion-time document embeddings.
        assert prefix == "search_query: "
        return [[0.0, 1.0, 0.0, 0.0]] * len(texts)


class ScoredReranker(Reranker):
    """Ranks pairs by their position (higher position = higher score)."""

    model = "fake-reranker"

    async def rerank(self, query, pairs):
        return [1.0 / (i + 1) for i in range(len(pairs))]


class FakeLLM(LLM):
    """Records the prompt and returns a canned, evidence-grounded answer."""

    model = "fake-llm"

    def __init__(self):
        self.calls = []

    async def complete(self, system, user):
        self.calls.append((system, user))
        return "Employees receive 20 days of annual leave (Leave Policy)."


@pytest.mark.asyncio
async def test_service_returns_grounded_result():
    """End-to-end orchestration: evidence, citations, and scores returned."""
    repo = FakeRepository(
        bm25_hits=[make_hit("a", "Annual leave accrues."), make_hit("b", "Sick leave policy.")],
        vector_hits=[make_hit("a", "Annual leave accrues."), make_hit("c", "Remote work policy.")],
    )
    service = KnowledgeService(repo, FakeEmbedder())

    result = await service.retrieve("How much annual leave do I get?")

    assert result.has_evidence
    assert result.confidence >= 0
    assert len(result.citations) > 0
    assert all(c.document_title == "Leave Policy" for c in result.citations)
    # "a" appears first in both lists -> top RRF score, but passthrough rerank keeps order
    assert result.chunks[0].text == "Annual leave accrues."


@pytest.mark.asyncio
async def test_service_applies_reranker_ordering():
    """With a real reranker, chunks are reordered by reranker score."""
    repo = FakeRepository(
        bm25_hits=[make_hit("a", "Annual leave."), make_hit("b", "Sick leave."), make_hit("c", "Remote.")],
        vector_hits=[make_hit("b", "Sick leave.")],
    )
    service = KnowledgeService(
        repo, FakeEmbedder(), reranker=ScoredReranker(),
        settings=RetrievalSettings(rerank_top_n=3),
    )

    result = await service.retrieve("leave")

    assert all(c.reranker_score is not None for c in result.chunks)
    assert result.chunks[0].reranker_score >= result.chunks[-1].reranker_score


@pytest.mark.asyncio
async def test_service_low_confidence_gate():
    """Weak evidence below the threshold is flagged as low confidence."""
    repo = FakeRepository(
        bm25_hits=[make_hit("only", "Unrelated snippet about parking.")],
        vector_hits=[],
    )
    service = KnowledgeService(
        repo, FakeEmbedder(), settings=RetrievalSettings(confidence_threshold=0.95)
    )

    result = await service.retrieve("nothing relevant")

    assert result.low_confidence is True


@pytest.mark.asyncio
async def test_service_forwards_metadata_filters():
    """Category/document_type/current_only are passed to both retrieval legs."""
    repo = FakeRepository(
        bm25_hits=[make_hit("a", "x", category="POLICY")],
        vector_hits=[make_hit("a", "x", category="POLICY")],
    )
    service = KnowledgeService(repo, FakeEmbedder())

    await service.retrieve(
        "query", category=DocumentCategory.POLICY, document_type="policy", current_only=False
    )

    assert repo.last_kwargs["bm25"]["category"] == DocumentCategory.POLICY
    assert repo.last_kwargs["bm25"]["document_type"] == "policy"
    assert repo.last_kwargs["bm25"]["current_only"] is False
    assert repo.last_kwargs["vector"]["category"] == DocumentCategory.POLICY


@pytest.mark.asyncio
async def test_service_expands_leaf_with_parent_section():
    """Small-to-big: matched leaves carry their enclosing section text."""
    hit = make_hit("a", "Sign the contract, then receive equipment.")
    repo = FakeRepositoryWithParents(
        bm25_hits=[hit],
        vector_hits=[],
        parent_contexts={hit.chunk_id: "Hybrid Work Procedure: onboarding steps."},
    )
    service = KnowledgeService(repo, FakeEmbedder())

    result = await service.retrieve("what happens after signing the contract")

    assert result.chunks[0].parent_context == "Hybrid Work Procedure: onboarding steps."
    # The grounded context shows the leaf inside its section.
    assert "Section: Annual Leave\nHybrid Work Procedure: onboarding steps." in (
        result.grounded_context
    )
    assert "Sign the contract, then receive equipment." in result.grounded_context


@pytest.mark.asyncio
async def test_service_empty_retrieval():
    """No hits yields empty result, zero confidence, and low-confidence flag."""
    service = KnowledgeService(FakeRepository([], []), FakeEmbedder())

    result = await service.retrieve("nothing")

    assert result.chunks == []
    assert result.grounded_context == ""
    assert result.confidence == 0.0
    assert result.low_confidence is True


def test_pass_through_reranker_preserves_order():
    reranker = PassThroughReranker()
    assert reranker.model == "passthrough"


@pytest.mark.asyncio
async def test_generate_answer_with_llm():
    """With an LLM and sufficient evidence, a polished answer is generated."""
    repo = FakeRepository(
        bm25_hits=[make_hit("a", "Employees receive 20 days of annual leave.")],
        vector_hits=[make_hit("a", "Employees receive 20 days of annual leave.")],
    )
    llm = FakeLLM()
    service = KnowledgeService(repo, FakeEmbedder(), llm=llm)

    result = await service.retrieve("how much annual leave?")
    answer = await service.generate_answer("how much annual leave?", result)

    assert answer == "Employees receive 20 days of annual leave (Leave Policy)."
    assert len(llm.calls) == 1
    system, user = llm.calls[0]
    assert "HR assistant" in system
    assert "how much annual leave?" in user
    assert "Leave Policy" in user  # source documents cited in the prompt


@pytest.mark.asyncio
async def test_generate_answer_skipped_when_no_llm():
    """No LLM configured => generate_answer returns None, retrieval still works."""
    repo = FakeRepository(
        bm25_hits=[make_hit("a", "Employees receive 20 days of annual leave.")],
        vector_hits=[make_hit("a", "Employees receive 20 days of annual leave.")],
    )
    service = KnowledgeService(repo, FakeEmbedder())

    result = await service.retrieve("how much annual leave?")
    assert await service.generate_answer("how much annual leave?", result) is None


@pytest.mark.asyncio
async def test_generate_answer_skipped_on_low_confidence():
    """Low-confidence retrieval is never handed to the LLM."""
    repo = FakeRepository(
        bm25_hits=[make_hit("only", "Unrelated snippet about parking.")],
        vector_hits=[],
    )
    llm = FakeLLM()
    service = KnowledgeService(
        repo, FakeEmbedder(), llm=llm,
        settings=RetrievalSettings(confidence_threshold=0.95),
    )

    result = await service.retrieve("nothing relevant")
    assert result.low_confidence is True
    assert await service.generate_answer("nothing relevant", result) is None
    assert llm.calls == []
