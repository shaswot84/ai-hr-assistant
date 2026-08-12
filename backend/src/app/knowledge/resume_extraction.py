from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from typing import Literal

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

MIN_USABLE_LENGTH = 40

# Signals used by `classify_resume` — deterministic, no LLM call, so a
# clearly-blank or clearly-unrelated upload is rejected without needing an
# AI provider. No single signal is required (contact info is commonly
# missing from real resumes), so several independent, differently-weighted
# signals are combined instead of gating on any one of them.
MIN_RESUME_LENGTH = 50
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d .()-]{8,}\d)")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

# Resume section headers: real resumes almost always have at least one of
# these as its own short line (e.g. "EDUCATION" on its own line), which is
# a much stronger signal than the word merely appearing inside a sentence
# (e.g. "Executive Summary" in an unrelated business report).
_SECTION_HEADERS = (
    "experience",
    "employment history",
    "work history",
    "professional experience",
    "education",
    "academic background",
    "skills",
    "technical skills",
    "core competencies",
    "qualifications",
    "certifications",
    "projects",
    "professional summary",
    "career objective",
    "objective",
    "achievements",
    "publications",
    "volunteer experience",
    "languages",
    "references",
    "curriculum vitae",
)
# Degree/education phrasing, useful for education-only resumes (e.g. new
# graduates) that may not have an explicit "EDUCATION" section header.
_DEGREE_KEYWORDS = (
    "bachelor",
    "master",
    "b.s.",
    "b.a.",
    "m.s.",
    "m.a.",
    "phd",
    "ph.d",
    "associate degree",
    "diploma",
    "university",
    "college",
)

_CLASSIFY_SYSTEM_PROMPT = (
    "You classify uploaded job-application files. Respond with ONLY a single "
    'valid JSON object: {"is_resume": boolean}. No markdown, no commentary.'
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


def _distinct_header_line_count(text: str) -> int:
    """Count distinct section headers that appear as their own short line."""
    matched: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lower()
        if not line or len(line) > 40:
            continue  # section headers are short standalone lines, not sentences
        for keyword in _SECTION_HEADERS:
            if keyword in line:
                matched.add(keyword)
    return len(matched)


def _has_line_structure(text: str) -> bool:
    """Resumes tend to be line-dense (many short lines) rather than prose paragraphs."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return False
    short_lines = [line for line in lines if len(line) <= 80]
    return len(short_lines) / len(lines) >= 0.6


def classify_resume(text: str) -> tuple[Literal["resume", "not_resume", "ambiguous"], str]:
    """Deterministic first-pass classification: confident accept, confident reject, or ambiguous.

    Combines five independent, weighted signals (contact info, distinct
    section headers, degree/education phrasing, a year/date, line-dense
    structure) rather than requiring any single one — a real resume missing
    just its contact details (a common case) or using unconventional
    headers can still score high enough to be confidently accepted.
    Genuinely borderline cases (e.g. a completion certificate with a name
    and a date) fall into "ambiguous" rather than being guessed either way.
    """
    if len(text) < MIN_RESUME_LENGTH:
        return "not_resume", "Not enough readable text was found in this file."

    lower = text.lower()
    has_contact = bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text))
    header_count = _distinct_header_line_count(text)
    has_degree = any(keyword in lower for keyword in _DEGREE_KEYWORDS)
    has_dates = bool(_YEAR_RE.search(text))
    has_structure = _has_line_structure(text)

    score = (
        (2 if has_contact else 0)
        + (3 if header_count >= 2 else 1 if header_count == 1 else 0)
        + (2 if has_degree else 0)
        + (1 if has_dates else 0)
        + (1 if has_structure else 0)
    )

    if score >= 3:
        return "resume", ""
    if score == 0:
        return "not_resume", (
            "This file doesn't look like a resume — no contact info, "
            "experience/education sections, or dates were found."
        )
    return "ambiguous", ""


async def verify_resume_with_llm(text: str) -> bool:
    """Ask the configured LLM to classify genuinely ambiguous text as a resume or not.

    Only meant for the "ambiguous" band `classify_resume` can't confidently
    decide on its own. Raises ChatProviderError if no AI provider is
    configured or the call fails — callers should fail open (accept) in
    that case rather than block a real candidate purely because the
    tie-breaker was unavailable.
    """
    provider = OllamaChatProvider()
    if not provider.is_configured():
        raise ChatProviderError("No AI provider is configured.")
    data = await provider.complete_json(
        system_prompt=_CLASSIFY_SYSTEM_PROMPT,
        user_prompt=(
            "Is the following document a resume/CV — a job candidate's own work "
            "history, education, and/or skills? Judge the content, not its "
            "formatting or completeness.\n\n"
            f"{text[:4000]}"
        ),
    )
    return bool(data.get("is_resume"))


def looks_like_resume(text: str) -> tuple[bool, str]:
    """Decide whether extracted text is plausibly a resume, for use in a sync context.

    Confident cases are resolved by `classify_resume` alone. Ambiguous cases
    get one LLM tie-break call via `asyncio.run` — safe here because this is
    only ever called from FastAPI's sync `def` route handlers, which run in
    a threadpool thread with no event loop of their own. Falls back to
    accepting (fail open) when no provider is configured or the call fails.

    Returns (is_resume, reason) — reason is a user-facing message when
    `is_resume` is False, empty string otherwise.
    """
    verdict, reason = classify_resume(text)
    if verdict != "ambiguous":
        return verdict == "resume", reason

    try:
        is_resume = asyncio.run(verify_resume_with_llm(text))
    except ChatProviderError:
        return True, ""
    if is_resume:
        return True, ""
    return False, "This file doesn't look like a resume."


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
