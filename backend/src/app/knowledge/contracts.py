"""Shared data contracts across the knowledge domain.

These dataclasses are the interface boundary between the ingestion pipeline,
the Knowledge Service, and the agent — keeping them decoupled.
"""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class IngestedChunk:
    """What the ingestion pipeline produces for a single chunk."""

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    chunk_index: int
    content: str
    processed_content: str
    page_number: int | None = None
    section_title: str | None = None
    token_count: int | None = None
    embedding: list[float] | None = None


@dataclass(frozen=True)
class IngestionProvenance:
    """Traceability the Knowledge Service uses for explainability."""

    parser_version: str | None = None
    chunking_strategy: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    pipeline_version: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieval result computed entirely by the Knowledge Service.

    ``retrieval_score`` (RRF), ``reranker_score`` and ``confidence`` are
    computed at query time; ingestion never writes them.
    """

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    document_title: str
    category: str
    page: int | None = None
    section_title: str | None = None
    text: str = ""
    retrieval_score: float = 0.0
    reranker_score: float | None = None
    confidence: float = 0.0
    provenance: IngestionProvenance | None = None


@dataclass(frozen=True)
class Citation:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    document_title: str
    category: str
    page: int | None = None
    section_title: str | None = None


@dataclass(frozen=True)
class KnowledgeResult:
    """Structured result the Knowledge Service returns to the agent."""

    grounded_context: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    chunks: list[RetrievedChunk] = field(default_factory=list)
    low_confidence: bool = False

    @property
    def has_evidence(self) -> bool:
        return bool(self.chunks) and self.confidence >= 0.0
