"""Shared data contracts across the knowledge domain.

These dataclasses are the interface boundary between the ingestion pipeline,
the Knowledge Service, and the agent — keeping them decoupled.
"""

from dataclasses import dataclass, field
from uuid import UUID

# anydoc format string (stored in document_version.mime_type) -> display label.
FILE_TYPE_LABELS: dict[str, str] = {
    "pdf": "PDF",
    "md": "Markdown",
    "markdown": "Markdown",
    "doc": "Word",
    "docx": "Word",
    "odt": "Word",
    "xls": "Excel",
    "xlsx": "Excel",
    "ods": "Excel",
    "csv": "CSV",
    "ppt": "PowerPoint",
    "pptx": "PowerPoint",
    "odp": "PowerPoint",
    "html": "HTML",
    "htm": "HTML",
    "txt": "Text",
    "rtf": "Text",
}


def friendly_file_type(mime_type: str | None) -> str:
    """Map an anydoc format string to a human-friendly label (PDF, Word, ...)."""
    if not mime_type:
        return ""
    return FILE_TYPE_LABELS.get(mime_type.strip().lower(), mime_type.upper())


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
    mime_type: str = ""
    page: int | None = None
    section_title: str | None = None
    text: str = ""
    # Enclosing section text fetched for small-to-big expansion: retrieval
    # matches leaf rows, and this carries the section the leaf lives in so
    # grounding can show both. Empty when the leaf has no section parent
    # (preamble directly under the document row) or expansion is off.
    parent_context: str = ""
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
    mime_type: str = ""
    page: int | None = None
    section_title: str | None = None


@dataclass(frozen=True)
class RestrictedDocument:
    """A document that matched the query but the requester may not access.

    Carries only identity metadata (title + allowlist) — never content — so
    the chatbot can reply "you cannot access this" without leaking the file.
    """

    title: str
    allowed_roles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeResult:
    """Structured result the Knowledge Service returns to the agent."""

    grounded_context: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    chunks: list[RetrievedChunk] = field(default_factory=list)
    low_confidence: bool = False
    # Documents the query would have matched but the requester cannot see.
    # Populated only when access control is applied AND no accessible
    # evidence was found; empty otherwise.
    restricted: list[RestrictedDocument] = field(default_factory=list)
    # True when no documents are indexed at all. The agent replies with a
    # deterministic "knowledge base is empty" message instead of a generic
    # refusal — and retrieval skips embedding entirely in this state.
    empty_knowledge_base: bool = False

    @property
    def has_evidence(self) -> bool:
        return bool(self.chunks) and self.confidence >= 0.0
