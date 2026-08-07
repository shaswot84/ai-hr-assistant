"""Knowledge Service: the read-side retrieval orchestrator.

This is the single entry point the agent uses to query the knowledge base.
It never touches pgvector/FTS/MinIO directly — it only talks to the
repository (PostgreSQL) and the Model Gateway (embedding + reranking).
"""

from dataclasses import replace
from uuid import UUID

from app.config.settings import RetrievalSettings
from app.knowledge.confidence import ConfidenceEstimator, LowConfidenceDetector
from app.knowledge.contracts import KnowledgeResult, RetrievedChunk
from app.knowledge.grounding import GroundingContextBuilder
from app.knowledge.models import DocumentCategory
from app.knowledge.ranking import reciprocal_rank_fusion
from app.knowledge.repository import HybridRetrievalRepository, RetrievalHit
from app.knowledge.reranker import PassThroughReranker
from app.model_gateway.interfaces import Embedder, Reranker

CURRENT_ONLY = True


class KnowledgeService:
    """Orchestrates query understanding → hybrid retrieval → fusion →
    reranking → grounding → citations → confidence estimation.
    """

    def __init__(
        self,
        repository: HybridRetrievalRepository,
        embedder: Embedder,
        *,
        settings: RetrievalSettings | None = None,
        reranker: Reranker | None = None,
        grounding_builder: GroundingContextBuilder | None = None,
        confidence_estimator: ConfidenceEstimator | None = None,
        low_confidence_detector: LowConfidenceDetector | None = None,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._settings = settings or RetrievalSettings()
        # Default to pass-through reranking when none is provided.
        self._reranker = reranker or PassThroughReranker()
        self._grounding = grounding_builder or GroundingContextBuilder(
            max_chunks=self._settings.rerank_top_n
        )
        self._confidence = confidence_estimator or ConfidenceEstimator(self._settings)
        self._low_confidence = low_confidence_detector or LowConfidenceDetector(
            self._settings
        )

    async def retrieve(
        self,
        query: str,
        *,
        category: DocumentCategory | None = None,
        document_type: str | None = None,
        current_only: bool = CURRENT_ONLY,
        top_k: int | None = None,
    ) -> KnowledgeResult:
        """Run the full retrieval pipeline for a query and return evidence.

        Steps:
        1. Embed the query (Model Gateway).
        2. Run BM25 and vector legs in parallel.
        3. Fuse both ranked lists with RRF.
        4. Rerank the fused candidates.
        5. Expand matched leaves with their enclosing section context
           (small-to-big).
        6. Estimate confidence and apply the low-confidence gate.
        7. Build grounded context + citations.
        """
        top_k = top_k or self._settings.top_k
        # nomic-embed-text is trained with task prefixes; matching the query
        # prefix against the document prefix used at ingestion improves
        # semantic retrieval substantially.
        query_embedding = (await self._embedder.embed([query], prefix="search_query: "))[0]

        # Run the legs sequentially: the repository is bound to a single
        # AsyncSession, which SQLAlchemy forbids using concurrently
        # ("concurrent operations are not permitted"). Both legs share the
        # already-computed query embedding, so there is nothing left to
        # parallelize at this layer.
        bm25_hits = await self._repository.bm25_search(
            query, top_k, current_only=current_only, category=category, document_type=document_type
        )
        vector_hits = await self._repository.vector_search(
            query_embedding,
            top_k,
            current_only=current_only,
            category=category,
            document_type=document_type,
        )

        # De-duplicate by chunk id so a chunk present in both legs is one row.
        hits_by_id = {hit.chunk_id: hit for hit in (*bm25_hits, *vector_hits)}

        fused = reciprocal_rank_fusion(
            [h.key for h in bm25_hits],
            [h.key for h in vector_hits],
            settings=self._settings,
            weights=[
                self._settings.bm25_weight,
                self._settings.vector_weight,
            ],
        )

        fused_chunks = self._to_retrieved_chunks(fused, hits_by_id)

        # True semantic signal from the vector leg (cosine similarity), used
        # as the quality signal when no reranker model is available.
        vector_scores = {hit.chunk_id: hit.score for hit in vector_hits}

        reranked = await self._rerank(query, fused_chunks, vector_scores)

        final = reranked[: self._settings.rerank_top_n]

        # Small-to-big: attach each matched leaf's enclosing section text so
        # grounding shows the section context the leaf lives in. Reranking and
        # confidence stay on the precise leaf; expansion only enriches what
        # the LLM actually sees.
        final = await self._expand(final)

        confidence = self._confidence.estimate(final)
        low_confidence = self._low_confidence.is_low(confidence, len(final))

        grounded_context, citations = self._grounding.build(final)

        return KnowledgeResult(
            grounded_context=grounded_context,
            citations=citations,
            confidence=confidence,
            chunks=final,
            low_confidence=low_confidence,
        )

    @staticmethod
    def _to_retrieved_chunks(
        fused: list[tuple[str, float]], hits_by_id: dict[UUID, RetrievalHit]
    ) -> list[RetrievedChunk]:
        """Convert fused (chunk_id, rrf_score) pairs into chunks."""
        chunks: list[RetrievedChunk] = []
        for key, score in fused:
            hit = hits_by_id.get(UUID(key))
            if hit is None:
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    document_version_id=hit.document_version_id,
                    version_number=hit.version_number,
                    document_title=hit.document_title,
                    category=hit.category,
                    page=hit.page,
                    section_title=hit.section_title,
                    text=hit.content,
                    retrieval_score=score,
                    provenance=hit.provenance,
                )
            )
        return chunks

    async def _expand(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Small-to-big: attach each matched leaf's enclosing section text.

        Retrieval matches leaf rows only; a leaf alone can be too narrow to
        answer. For every selected chunk we fetch the text of its immediate
        parent section and carry it on ``parent_context`` so grounding shows
        the leaf inside its section. Leaves whose parent is the document root
        get no expansion (the repository skips document rows deliberately).
        """
        if not chunks:
            return chunks
        parent_texts = await self._repository.fetch_parent_context(
            [c.chunk_id for c in chunks]
        )
        return [
            replace(c, parent_context=parent_texts.get(c.chunk_id, "")) for c in chunks
        ]

    async def _rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        vector_scores: dict[UUID, float] | None = None,
    ) -> list[RetrievedChunk]:
        """Attach reranker scores and, unless pass-through, reorder by them.

        Without a reranker model, the real vector cosine similarity is used
        as the quality signal (the pass-through's flat 0.5 carries no
        information, so it would make both ordering and confidence noise).
        """
        if not chunks:
            return chunks
        if self._reranker.model == "passthrough":
            return self._score_by_vector_similarity(chunks, vector_scores)
        pairs = [(query, chunk.text) for chunk in chunks]
        scores = await self._reranker.rerank(query, pairs)

        reranked = [
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_version_id=c.document_version_id,
                version_number=c.version_number,
                document_title=c.document_title,
                category=c.category,
                page=c.page,
                section_title=c.section_title,
                text=c.text,
                retrieval_score=c.retrieval_score,
                reranker_score=float(score),
                confidence=c.confidence,
                provenance=c.provenance,
            )
            for c, score in zip(chunks, scores, strict=True)
        ]
        reranked.sort(key=lambda c: c.reranker_score or 0.0, reverse=True)
        return reranked

    @staticmethod
    def _score_by_vector_similarity(
        chunks: list[RetrievedChunk], vector_scores: dict[UUID, float] | None
    ) -> list[RetrievedChunk]:
        """Order by real cosine similarity; BM25-only hits rank below.

        A chunk may appear in the vector leg, the BM25 leg, or both. Cosine
        similarity is a genuine [0, 1] semantic score, so it ranks the
        relevant leaves first and gives the confidence estimator a real
        signal. Lexical-only hits (no embedding distance) fall back to their
        RRF score so they still sort, but below any semantically matched leaf.
        """
        vector_scores = vector_scores or {}
        reranked = [
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_version_id=c.document_version_id,
                version_number=c.version_number,
                document_title=c.document_title,
                category=c.category,
                page=c.page,
                section_title=c.section_title,
                text=c.text,
                retrieval_score=c.retrieval_score,
                reranker_score=vector_scores.get(c.chunk_id),
                confidence=c.confidence,
                provenance=c.provenance,
            )
            for c in chunks
        ]
        # Chunks with a cosine score first (higher = better); BM25-only chunks
        # sort by their RRF score below any scored leaf.
        reranked.sort(
            key=lambda c: (
                c.reranker_score is None,
                -(c.reranker_score or c.retrieval_score or 0.0),
            )
        )
        return reranked
