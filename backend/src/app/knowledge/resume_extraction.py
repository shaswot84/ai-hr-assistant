from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

MIN_USABLE_LENGTH = 40

# Signals used by `looks_like_resume` — deterministic, no LLM call, so a
# garbage upload (blank page, random report, non-resume document) is
# rejected up front regardless of whether an AI provider is configured.
MIN_RESUME_LENGTH = 200
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d .()-]{8,}\d)")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_SECTION_KEYWORDS = (
    "experience",
    "employment",
    "education",
    "skills",
    "qualifications",
    "certification",
    "projects",
    "summary",
    "objective",
    "work history",
    "curriculum vitae",
)


class UnsupportedFileError(Exception):
    """Raised when a resume is neither a PDF nor a DOCX file."""


@dataclass
class ExtractResult:
    """Result of resume extraction: the extracted text plus an optional warning."""

    text: str
    warning: str | None = None


def extract_text(data: bytes, filename: str, content_type: str) -> ExtractResult:
    """Extract text from a PDF or DOCX resume."""
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
    """Extract and normalize text from a PDF, returning a warning on low yield."""
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
    """Extract and normalize text from a DOCX, preserving tables as pipe-separated rows."""
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


def looks_like_resume(text: str) -> tuple[bool, str]:
    """Heuristically decide whether extracted text is plausibly a resume.

    Deterministic and LLM-free: requires enough readable content plus at
    least two of three independent resume signals (contact info, a resume
    section keyword, a year/date). A blank page, scanned image, or an
    unrelated document (report, cover letter, ID scan) typically has zero
    or one of these, so it's rejected without needing model access.

    Returns (is_resume, reason) — reason is a user-facing message when
    `is_resume` is False, empty string otherwise.
    """
    if len(text) < MIN_RESUME_LENGTH:
        return False, "Not enough readable text was found in this file."

    lower = text.lower()
    has_contact = bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text))
    has_section = any(keyword in lower for keyword in _SECTION_KEYWORDS)
    has_dates = len(_YEAR_RE.findall(text)) >= 2

    if sum([has_contact, has_section, has_dates]) < 2:
        return False, (
            "This file doesn't look like a resume — no contact info, "
            "experience/education sections, or dates were found."
        )
    return True, ""


def _iter_block_items(document: Document):
    """Yield paragraphs and tables in document order (python-docx doesn't do this natively)."""
    parent_elm = document.element.body
    for child in parent_elm.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _normalize(text: str) -> str:
    """Normalize line endings, trailing whitespace, and excessive blank lines."""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
