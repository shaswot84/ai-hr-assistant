from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

MIN_USABLE_LENGTH = 40


class UnsupportedFileError(Exception):
    pass


@dataclass
class ExtractResult:
    text: str
    warning: str | None = None


def extract_text(data: bytes, filename: str, content_type: str) -> ExtractResult:
    """Extract text from a PDF or DOCX resume (ported from ~/projects/resume)."""
    lower = filename.lower()
    is_pdf = content_type == "application/pdf" or lower.endswith(".pdf")
    is_docx = (
        content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or lower.endswith(".docx")
    )

    if is_pdf:
        return _extract_from_pdf(data)
    if is_docx:
        return _extract_from_docx(data)

    raise UnsupportedFileError("Unsupported file type. Please upload a PDF or DOCX resume.")


def _extract_from_pdf(data: bytes) -> ExtractResult:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = _normalize("\n".join(pages))
    except Exception as err:  # noqa: BLE001 - surface as graceful warning, not crash
        return ExtractResult(
            text="",
            warning=(
                f"Could not extract text from this PDF ({err}). "
                "It may be corrupted, password-protected, or image-based."
            ),
        )

    if len(text) < MIN_USABLE_LENGTH:
        return ExtractResult(
            text=text,
            warning=(
                "Very little text could be extracted from this PDF. It may be a scanned "
                "image or use an unusual layout — the review may be incomplete."
            ),
        )
    return ExtractResult(text=text)


def _extract_from_docx(data: bytes) -> ExtractResult:
    try:
        document = Document(io.BytesIO(data))
        lines: list[str] = []
        for block in _iter_block_items(document):
            if isinstance(block, Paragraph):
                if block.text.strip():
                    lines.append(block.text)
            elif isinstance(block, Table):
                for row in block.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        lines.append(" | ".join(cells))
        text = _normalize("\n".join(lines))
    except Exception as err:  # noqa: BLE001
        return ExtractResult(
            text="",
            warning=(
                f"Could not extract text from this DOCX file ({err}). "
                "It may be corrupted or in an unsupported format."
            ),
        )

    if len(text) < MIN_USABLE_LENGTH:
        return ExtractResult(
            text=text,
            warning=(
                "Very little text could be extracted from this DOCX file. "
                "The review may be incomplete."
            ),
        )
    return ExtractResult(text=text)


def _iter_block_items(document: Document):
    """Yield paragraphs and tables in document order (python-docx doesn't do this natively)."""
    parent_elm = document.element.body
    for child in parent_elm.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
