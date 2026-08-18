"""Knowledge Service: the read-side retrieval orchestrator.

This is the single entry point the agent uses to query the knowledge base.
It never touches pgvector/FTS/MinIO directly — it only talks to the
repository (PostgreSQL) and the Model Gateway (embedding + reranking).
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID

from app.config.settings import RetrievalSettings
from app.knowledge.confidence import ConfidenceEstimator, LowConfidenceDetector
from app.knowledge.contracts import KnowledgeResult, RestrictedDocument, RetrievedChunk
from app.knowledge.grounding import GroundingContextBuilder
from app.knowledge.models import DocumentCategory
from app.knowledge.ranking import reciprocal_rank_fusion
from app.knowledge.repository import HybridRetrievalRepository, RetrievalHit
from app.knowledge.reranker import PassThroughReranker
from app.model_gateway.interfaces import LLM, Embedder, Reranker

logger = logging.getLogger(__name__)

CURRENT_ONLY = True

# System prompt for the generation LLM: answer only from the evidence, cite
# the source documents, refuse gracefully when the context cannot answer.
_GENERATION_SYSTEM = """You are an HR assistant for Summit Technologies Pvt. Ltd.
Answer the user's question in a clear, professional, concise way using ONLY the
grounded context below. Follow these rules strictly:

1. Base every claim on the provided evidence. Never invent facts, numbers, or
   policies that are not in the context.
2. After EVERY claim, cite the evidence block(s) it came from with their
   bracketed number(s), e.g. "[1]" or "[2, 3]". The numbers are the [N]
   markers printed at the start of each GROUNDED CONTEXT block. End each
   claim with at least one marker.
3. If the context does not contain enough information to answer the question,
   say so honestly and suggest what additional document might help.
4. Use plain Markdown: short paragraphs or bullets. Do not add headings or
   citations beyond the bracketed markers."""


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
        llm: LLM | None = None,
        grounding_builder: GroundingContextBuilder | None = None,
        confidence_estimator: ConfidenceEstimator | None = None,
        low_confidence_detector: LowConfidenceDetector | None = None,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._settings = settings or RetrievalSettings()
        # Default to pass-through reranking when none is provided.
        self._reranker = reranker or PassThroughReranker()
        self._llm = llm
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
        current_only: bool = CURRENT_ONLY,
        top_k: int | None = None,
        access_roles: list[str] | None = None,
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

        ``access_roles`` gates every leg to documents whose ``role_access``
        allowlist contains the requester's role(s); ``None`` disables access
        control (HR admin / unrestricted callers). When access control is on
        and NO accessible evidence is found, a cheap BM25 probe runs to
        surface ``restricted`` matches — documents the query hit but the
        requester cannot see (identity only, never content) — so the agent
        can reply "you cannot access this" instead of pretending the
        document does not exist.

        An empty knowledge base (no INDEXED documents) short-circuits before
        embedding: the result carries ``empty_knowledge_base=True`` so the
        agent can say "no documents yet" without a wasted (or, when the
        embedder is unreachable, failing) model call. A failed embedding
        call is also degraded to an empty result instead of raising — search
        must never hard-fail because the embedder is down.
        """
        top_k = top_k or self._settings.top_k

        if not await self._repository.has_indexed_documents():
            return KnowledgeResult(grounded_context="", empty_knowledge_base=True)

        # nomic-embed-text is trained with task prefixes; matching the query
        # prefix against the document prefix used at ingestion improves
        # semantic retrieval substantially.
        try:
            query_embedding = (await self._embedder.embed([query], prefix="search_query: "))[0]
        except Exception:  # noqa: BLE001 - a down embedder degrades to an empty result
            logger.warning("query embedding failed; serving an empty result", exc_info=True)
            return KnowledgeResult(grounded_context="", low_confidence=True)

        # Run the legs sequentially: the repository is bound to a single
        # AsyncSession, which SQLAlchemy forbids using concurrently
        # ("concurrent operations are not permitted"). Both legs share the
        # already-computed query embedding, so there is nothing left to
        # parallelize at this layer.
        bm25_hits = await self._repository.bm25_search(
            query,
            top_k,
            current_only=current_only,
            category=category,
            access_roles=access_roles,
        )
        vector_hits = await self._repository.vector_search(
            query_embedding,
            top_k,
            current_only=current_only,
            category=category,
            access_roles=access_roles,
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

        restricted: list[RestrictedDocument] = []
        if access_roles is not None and not citations:
            restricted = await self._repository.restricted_matches(
                query, access_roles, current_only=current_only
            )

        return KnowledgeResult(
            grounded_context=grounded_context,
            citations=citations,
            confidence=confidence,
            chunks=final,
            low_confidence=low_confidence,
            restricted=restricted,
        )

    async def generate_answer(
        self, query: str, result: KnowledgeResult, *, history: str | None = None
    ) -> str | None:
        """Produce a polished, grounded answer from a retrieval result.

        Returns ``None`` when no LLM is configured, retrieval is
        low-confidence (not enough evidence to answer safely), or generation
        fails. The caller then serves the grounded context as-is.

        ``history`` is an optional pre-formatted transcript block (see
        ``agents.context.history_text``) that makes the answer
        conversation-aware; when given it is placed above the question.
        """
        if self._llm is None:
            return None
        if result.low_confidence or not result.citations:
            return None
        sources = ", ".join(
            sorted({c.document_title for c in result.citations})
        )
        user = f"QUESTION:\n{query}\n\nSOURCES: {sources}\n\nGROUNDED CONTEXT:\n{result.grounded_context}"
        if history:
            user = f"CONVERSATION HISTORY:\n{history}\n\n{user}"
        try:
            return await self._llm.complete(_GENERATION_SYSTEM, user)
        except Exception:  # noqa: BLE001 - never fail search because of the LLM
            return None

    async def stream_answer(
        self, query: str, result: KnowledgeResult, *, history: str | None = None
    ) -> AsyncIterator[str]:
        """Stream a grounded answer token by token.

        Same gating and prompt as :meth:`generate_answer` — yields nothing
        when no LLM is configured, retrieval is low-confidence, or generation
        fails mid-stream. The caller (SSE endpoint) terminates the stream the
        moment this generator is exhausted.
        """
        if self._llm is None:
            return
        if result.low_confidence or not result.citations:
            return
        sources = ", ".join(
            sorted({c.document_title for c in result.citations})
        )
        user = f"QUESTION:\n{query}\n\nSOURCES: {sources}\n\nGROUNDED CONTEXT:\n{result.grounded_context}"
        if history:
            user = f"CONVERSATION HISTORY:\n{history}\n\n{user}"
        try:
            async for token in self._llm.stream(_GENERATION_SYSTEM, user):
                yield token
        except Exception:  # noqa: BLE001 - never fail search because of the LLM
            return

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
