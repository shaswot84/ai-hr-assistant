"""Knowledge Service: the read-side retrieval orchestrator.

This is the single entry point the agent uses to query the knowledge base.
It never touches pgvector/FTS/MinIO directly — it only talks to the
repository (PostgreSQL) and the Model Gateway (embedding + reranking).
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from app.config.settings import RetrievalSettings
from app.knowledge.confidence import ConfidenceEstimator, LowConfidenceDetector
from app.knowledge.contracts import KnowledgeResult, RestrictedDocument, RetrievedChunk
from app.knowledge.grounding import GroundingContextBuilder
from app.knowledge.markers import renumber_markers
from app.knowledge.models import DocumentCategory
from app.knowledge.ranking import reciprocal_rank_fusion
from app.knowledge.repository import HybridRetrievalRepository, RetrievalHit
from app.knowledge.reranker import PassThroughReranker
from app.model_gateway.interfaces import LLM, Embedder, Reranker
from app.observability import async_trace_span, set_retrieval_documents, trace_span

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
        """Run the full retrieval pipeline for a query and return evidence."""
        top_k = top_k or self._settings.top_k

        async with async_trace_span(
            "rag.retrieve",
            span_kind=OpenInferenceSpanKindValues.RETRIEVER,
            attributes={
                SpanAttributes.INPUT_VALUE: query,
                "rag.category": str(category) if category else None,
                "rag.top_k": top_k,
                "rag.access_roles": access_roles,
            },
        ) as span:
            if not await self._repository.has_indexed_documents():
                span.set_attribute("rag.empty_knowledge_base", True)
                span.set_attribute("rag.status", "refused")
                span.set_attribute("rag.refusal_reason", "empty_kb")
                return KnowledgeResult(grounded_context="", empty_knowledge_base=True)

            try:
                with trace_span(
                    "rag.embedding",
                    span_kind=OpenInferenceSpanKindValues.EMBEDDING,
                    attributes={"rag.query": query},
                ):
                    query_embedding = (await self._embedder.embed([query], prefix="search_query: "))[0]
            except Exception:
                logger.warning("query embedding failed; serving an empty result", exc_info=True)
                span.set_attribute("rag.status", "refused")
                span.set_attribute("rag.refusal_reason", "embedding_failed")
                return KnowledgeResult(grounded_context="", low_confidence=True)

            with trace_span(
                "rag.search.bm25",
                span_kind=OpenInferenceSpanKindValues.RETRIEVER,
                attributes={"rag.top_k": top_k},
            ):
                bm25_hits = await self._repository.bm25_search(
                    query,
                    top_k,
                    current_only=current_only,
                    category=category,
                    access_roles=access_roles,
                )

            with trace_span(
                "rag.search.vector",
                span_kind=OpenInferenceSpanKindValues.RETRIEVER,
                attributes={"rag.top_k": top_k},
            ):
                vector_hits = await self._repository.vector_search(
                    query_embedding,
                    top_k,
                    current_only=current_only,
                    category=category,
                    access_roles=access_roles,
                )

            # De-duplicate by chunk id so a chunk present in both legs is one row.
            hits_by_id = {hit.chunk_id: hit for hit in (*bm25_hits, *vector_hits)}

            with trace_span(
                "rag.ranking.rrf",
                span_kind=OpenInferenceSpanKindValues.RERANKER,
                attributes={"rag.bm25_hits": len(bm25_hits), "rag.vector_hits": len(vector_hits)},
            ):
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

            # True semantic signal from the vector leg (cosine similarity)
            vector_scores = {hit.chunk_id: hit.score for hit in vector_hits}

            with trace_span(
                "rag.reranker",
                span_kind=OpenInferenceSpanKindValues.RERANKER,
                attributes={
                    "rag.reranker_model": getattr(self._reranker, "model", "unknown"),
                    "rag.candidates_in_count": len(fused_chunks),
                },
            ) as rerank_span:
                reranked = await self._rerank(query, fused_chunks, vector_scores)
                final = reranked[: self._settings.rerank_top_n]
                rerank_span.set_attribute("rag.candidates_out_count", len(final))
                if final:
                    top_score = (
                        final[0].reranker_score
                        if final[0].reranker_score is not None
                        else final[0].retrieval_score
                    )
                    if top_score is not None:
                        rerank_span.set_attribute("rag.rerank_score_top", float(top_score))
                    rank_shift = bool(fused_chunks and fused_chunks[0].chunk_id != final[0].chunk_id)
                    rerank_span.set_attribute("rag.rank_shift", rank_shift)

            # Small-to-big parent context expansion
            base_chars = sum(len(c.text) for c in final)
            with trace_span(
                "rag.parent_expansion",
                span_kind=OpenInferenceSpanKindValues.CHAIN,
                attributes={"rag.candidates_in": len(final)},
            ) as expand_span:
                final = await self._expand(final)
                expanded_chars = sum(len(c.parent_context or "") + len(c.text) for c in final)
                expanded_count = sum(1 for c in final if c.parent_context)
                ratio = round(expanded_chars / max(base_chars, 1), 2)
                expand_span.set_attribute("rag.parent_expansion_ratio", ratio)
                expand_span.set_attribute("rag.expanded_chunks_count", expanded_count)

            with trace_span(
                "rag.confidence",
                span_kind=OpenInferenceSpanKindValues.GUARDRAIL,
            ):
                confidence = self._confidence.estimate(final)
                low_confidence = self._low_confidence.is_low(confidence, len(final))

            with trace_span(
                "rag.grounding",
                span_kind=OpenInferenceSpanKindValues.CHAIN,
            ):
                grounded_context, citations = self._grounding.build(final)

            restricted: list[RestrictedDocument] = []
            if access_roles is not None and not citations:
                restricted = await self._repository.restricted_matches(
                    query, access_roles, current_only=current_only
                )

            # Set OpenInference RETRIEVAL_DOCUMENTS on the retriever span
            set_retrieval_documents(span, final)
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, grounded_context)
            span.set_attribute("rag.confidence", float(confidence))
            span.set_attribute("rag.low_confidence", bool(low_confidence))
            span.set_attribute("rag.citation_count", len(citations))

            if restricted:
                span.set_attribute("rag.status", "refused")
                span.set_attribute("rag.refusal_reason", "restricted")
                span.set_attribute("rag.restricted_count", len(restricted))
            elif low_confidence or not citations:
                span.set_attribute("rag.status", "refused")
                span.set_attribute(
                    "rag.refusal_reason",
                    "low_confidence" if low_confidence else "no_citations",
                )
            else:
                span.set_attribute("rag.status", "success")

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
        """Produce a polished, grounded answer from a retrieval result."""
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

        async with async_trace_span(
            "rag.generate_answer",
            span_kind=OpenInferenceSpanKindValues.CHAIN,
            attributes={
                "rag.query": query,
                "rag.citation_count": len(result.citations),
            },
        ) as gen_span:
            try:
                answer = await self._llm.complete(_GENERATION_SYSTEM, user)
            except Exception:  # noqa: BLE001 - never fail search because of the LLM
                return None
            final_answer = renumber_markers(answer, list(range(1, len(result.citations) + 1)))
            gen_span.set_attribute(SpanAttributes.OUTPUT_VALUE, final_answer)
            return final_answer

    async def stream_answer(
        self, query: str, result: KnowledgeResult, *, history: str | None = None
    ) -> AsyncIterator[str]:
        """Stream a grounded answer token by token."""
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
                    mime_type=hit.mime_type or "",
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
                mime_type=c.mime_type,
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
                mime_type=c.mime_type,
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
