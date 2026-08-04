"""Grounding: turns retrieved chunks into the LLM prompt context + citations."""

from collections.abc import Iterable

from app.knowledge.contracts import Citation, RetrievedChunk


class GroundingContextBuilder:
    """Builds the grounded context passed to the LLM plus citations."""

    def __init__(self, max_chunks: int | None = None) -> None:
        self._max_chunks = max_chunks

    def build(
        self, chunks: Iterable[RetrievedChunk]
    ) -> tuple[str, list[Citation]]:
        chunks = list(chunks)
        if self._max_chunks is not None:
            chunks = chunks[: self._max_chunks]

        citations: list[Citation] = []
        blocks: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            citations.append(self._to_citation(chunk))
            location = self._location(chunk)
            prefix = f"[{index}]" + (f" ({location})" if location else "")
            blocks.append(f"{prefix} {chunk.text.strip()}")

        return "\n\n".join(blocks), citations

    @staticmethod
    def _to_citation(chunk: RetrievedChunk) -> Citation:
        return Citation(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            version_number=chunk.version_number,
            document_title=chunk.document_title,
            category=chunk.category,
            page=chunk.page,
            section_title=chunk.section_title,
        )

    @staticmethod
    def _location(chunk: RetrievedChunk) -> str:
        parts = [chunk.document_title]
        if chunk.section_title:
            parts.append(chunk.section_title)
        if chunk.page is not None:
            parts.append(f"p.{chunk.page}")
        return ", ".join(parts)
