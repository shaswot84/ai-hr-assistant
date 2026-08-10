"""Grounding: turns retrieved chunks into the LLM prompt context + citations."""

import re
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
            blocks.append(f"{prefix} {self._render_text(chunk)}")

        return "\n\n".join(blocks), citations

    @staticmethod
    def _render_text(chunk: RetrievedChunk) -> str:
        """The chunk's text, prefixed with its enclosing section when present.

        Small-to-big expansion attaches the section the leaf lives in; render
        it above the leaf so the LLM sees the leaf inside its section. The
        citation still points at the leaf (the precise evidence).
        """
        text = chunk.text.strip()
        if not chunk.parent_context:
            return text
        label = f"Section: {chunk.section_title}" if chunk.section_title else "Context"
        parent = chunk.parent_context.strip()
        # Section rows include the leaf's own text; drop the exact duplicate so
        # the grounded context does not show the same content twice.
        if text and text in parent:
            parent = parent.replace(text, "", 1)
        parent = re.sub(r"\n{3,}", "\n\n", parent).strip()
        if not parent:
            return text
        return f"{label}\n{parent}\n\n{text}"

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
