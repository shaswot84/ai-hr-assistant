import asyncio
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
        top_k = top_k or self._settings.top_k
        query_embedding = (await self._embedder.embed([query]))[0]

        bm25_hits, vector_hits = await asyncio.gather(
            self._repository.bm25_search(
                query, top_k, current_only=current_only, category=category, document_type=document_type
            ),
            self._repository.vector_search(
                query_embedding,
                top_k,
                current_only=current_only,
                category=category,
                document_type=document_type,
            ),
        )

        hits_by_id = {hit.chunk_id: hit for hit in (*bm25_hits, *vector_hits)}

        fused = reciprocal_rank_fusion(
            [h.key for h in bm25_hits],
            [h.key for h in vector_hits],
            settings=self._settings,
        )

        fused_chunks = self._to_retrieved_chunks(fused, hits_by_id)

        reranked = await self._rerank(query, fused_chunks)

        final = reranked[: self._settings.rerank_top_n]
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

    async def _rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return chunks
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

        if self._reranker.model != "passthrough":
            reranked.sort(key=lambda c: c.reranker_score or 0.0, reverse=True)
        return reranked
