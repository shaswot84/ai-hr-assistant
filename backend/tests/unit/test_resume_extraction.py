from __future__ import annotations

import pymupdf
import pytest

from app.knowledge.resume_extraction import (
    assess_parsability,
    classify_resume,
    extract_text,
    is_ats_friendly,
    looks_like_resume,
)


def _build_pdf_with_positioned_words(lines: list[list[str]]) -> bytes:
    """Build a one-page PDF where each word is its own glyph run placed by
    x/y position, with no literal space character anywhere in the content
    stream — the same mechanism many LaTeX resume templates use to lay out
    justified text. A naive extractor that only splits on space codepoints
    reads this as one run-together blob per line; a correct one reconstructs
    words from the gaps between glyph runs.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72.0
    for words in lines:
        x = 72.0
        for word in words:
            page.insert_text((x, y), word, fontsize=11)
            x += pymupdf.get_text_length(word, fontsize=11) + 3
        y += 16
    buf = doc.tobytes()
    doc.close()
    return buf


REAL_RESUME_TEXT = """
Jane Doe
jane.doe@example.com | (555) 123-4567 | San Francisco, CA

SUMMARY
Backend engineer with 6 years of experience building scalable APIs.

EXPERIENCE
Senior Backend Engineer, Acme Corp — 2021 to 2026
- Led the migration of the monolith to microservices.
- Mentored three junior engineers.

Backend Engineer, Startup Inc — 2019 to 2021
- Built the payments service from scratch.

EDUCATION
B.S. Computer Science, State University, 2019

SKILLS
Python, FastAPI, PostgreSQL, Docker, Kubernetes
"""

# A short, plain resume as a new graduate might produce in MS Word — name,
# education, skills, no contact info. This is the exact case that used to
# be wrongly rejected: too short to clear the old 200-char floor, and even
# padded out, missing contact info meant it never reached 2 of 3 signals.
SHORT_RESUME_NO_CONTACT = """John Smith
EDUCATION
B.S. Computer Science, State University, 2019
SKILLS
Python, Excel, Communication"""


async def test_looks_like_resume_accepts_real_resume():
    is_resume, reason = await looks_like_resume(REAL_RESUME_TEXT)
    assert is_resume is True
    assert reason == ""


async def test_looks_like_resume_accepts_short_resume_missing_contact_info():
    """Regression test: a real (if sparse) resume missing contact info must
    not be rejected just because one signal is absent.
    """
    is_resume, reason = await looks_like_resume(SHORT_RESUME_NO_CONTACT)
    assert is_resume is True
    assert reason == ""


async def test_looks_like_resume_accepts_resume_with_single_header_and_degree():
    """Only one explicit section header ("SKILLS"), but a degree phrase and
    a date make up for it — still confidently a resume.
    """
    text = """Alex Kim
SKILLS
Java, SQL, Project Management
Graduated from Boston University in 2020 with a Bachelor of Arts."""
    is_resume, reason = await looks_like_resume(text)
    assert is_resume is True
    assert reason == ""


async def test_looks_like_resume_rejects_blank_text():
    is_resume, reason = await looks_like_resume("")
    assert is_resume is False
    assert "readable text" in reason


async def test_looks_like_resume_rejects_short_text():
    is_resume, reason = await looks_like_resume("Thanks for your time, see attached.")
    assert is_resume is False
    assert "readable text" in reason


async def test_looks_like_resume_rejects_unrelated_long_document():
    """A long document with zero resume signals (no contact info, no section
    header lines, no degree phrasing, no dates, no line structure) is
    confidently rejected without needing an LLM call — e.g. a business report.
    """
    unrelated = (
        "This quarterly report summarizes company performance across several "
        "business units and outlines strategic priorities for the coming period. "
    ) * 5
    is_resume, reason = await looks_like_resume(unrelated)
    assert is_resume is False
    assert "doesn't look like a resume" in reason


def test_classify_resume_flags_single_signal_document_as_ambiguous():
    """Contact info alone (e.g. a business card scan) isn't enough for a
    confident verdict either way — it's exactly what the ambiguous band is
    for, so the LLM tie-break (or fail-open default) decides, not a guess
    baked into the heuristic.
    """
    text = "Jane Doe jane.doe@example.com Thank you for reaching out. " * 6
    verdict, reason = classify_resume(text)
    assert verdict == "ambiguous"
    assert reason == ""


async def test_looks_like_resume_fails_open_on_ambiguous_without_llm_configured():
    """No AI provider is configured in the test environment, so an ambiguous
    case must fail open (accept) rather than silently block a real candidate
    just because no tie-breaker was available.

    Regression: this test runs inside a live event loop (pytest-asyncio),
    exactly like the async apply routes. The old sync implementation called
    `asyncio.run()` for ambiguous cases and crashed every such upload with
    "RuntimeError: asyncio.run() cannot be called from a running event loop"
    (HTTP 500). The awaited tie-break must instead degrade to fail-open.
    """
    text = "Jane Doe jane.doe@example.com Thank you for reaching out. " * 6
    is_resume, reason = await looks_like_resume(text)
    assert is_resume is True
    assert reason == ""


@pytest.mark.parametrize(
    "text",
    [
        REAL_RESUME_TEXT,
        SHORT_RESUME_NO_CONTACT,
    ],
)
def test_classify_resume_accepts_without_llm(text):
    """Both example resumes should resolve to a confident 'resume' verdict
    from the deterministic pass alone — never falling into 'ambiguous' and
    needing an LLM call for a clearly-real resume.
    """
    verdict, _ = classify_resume(text)
    assert verdict == "resume"


# ── ATS-parsability check ──────────────────────────────────────────────

# Simulates a multi-column layout flattened by a bad PDF extractor: every
# word runs into the next with no spaces, everything lands on one line, and
# there are no recognizable section headers — three independent signals of
# scrambled extraction, even though the total character count is well past
# the "is this a resume" floor.
GARBLED_MERGED_TEXT = (
    "JohnDoeBackendEngineerWithSixYearsOfProfessionalSoftwareDevelopmentExperience"
    "BuildingScalableDistributedSystemsUsingPythonJavaAndGoAcrossMultipleCloudPlatforms"
    "IncludingAWSAzureAndGCPWithExpertiseInKubernetesDockerAndMicroservicesArchitecture"
    "PriorToThisRoleTheyWorkedAtStartupIncFrom2019To2021BuildingThePaymentsServiceFromScratch"
    "TheyHoldABachelorOfScienceInComputerScienceFromStateUniversityGraduated2019"
)

# A real resume's content, but flattened into one flowing paragraph with no
# line breaks and no section headers — plausible output of an extractor
# that drops structure without merging words. Genuinely ambiguous: normal
# word lengths (nothing merged), but no headers and no line structure.
FLATTENED_PROSE_TEXT = (
    "John Doe is a backend engineer with six years of experience building scalable "
    "APIs. He previously worked at Acme Corp as a senior backend engineer from 2021 "
    "to 2026, where he led the migration of the monolith to microservices and "
    "mentored three junior engineers. Before that, he worked at Startup Inc as a "
    "backend engineer from 2019 to 2021, building the payments service from "
    "scratch. He holds a Bachelor of Science in Computer Science from State "
    "University, 2019. His skills include Python, FastAPI, PostgreSQL, Docker, "
    "and Kubernetes."
)


def test_assess_parsability_accepts_well_formatted_resume():
    verdict, reason = assess_parsability(REAL_RESUME_TEXT)
    assert verdict == "ok"
    assert reason == ""


def test_assess_parsability_rejects_merged_words_with_no_structure():
    """Regression case for the core ask: a resume that passes the 'is this
    a resume' classifier (real words, real content) can still be
    unreliable to screen if the extraction scrambled it — this must be
    caught deterministically, without needing an LLM call.
    """
    verdict, reason = assess_parsability(GARBLED_MERGED_TEXT)
    assert verdict == "poor"
    assert "couldn't be reliably parsed" in reason


def test_assess_parsability_flags_flattened_prose_as_ambiguous():
    """Normal word lengths (nothing merged), but no headers and no line
    structure — not confidently bad on its own, so it's the LLM tie-break's
    call, same as `classify_resume`'s ambiguous band.
    """
    verdict, reason = assess_parsability(FLATTENED_PROSE_TEXT)
    assert verdict == "ambiguous"
    assert reason == ""


def test_assess_parsability_rejects_too_short_text():
    verdict, reason = assess_parsability("Some short text.")
    assert verdict == "poor"
    assert "Not enough text" in reason


async def test_is_ats_friendly_accepts_well_formatted_resume():
    is_friendly, reason = await is_ats_friendly(REAL_RESUME_TEXT)
    assert is_friendly is True
    assert reason == ""


async def test_is_ats_friendly_rejects_garbled_resume_without_llm():
    is_friendly, reason = await is_ats_friendly(GARBLED_MERGED_TEXT)
    assert is_friendly is False
    assert "couldn't be reliably parsed" in reason


async def test_is_ats_friendly_fails_open_on_ambiguous_without_llm_configured():
    """No AI provider is configured in the test environment, so an
    ambiguous formatting case must fail open (accept) rather than block a
    real candidate just because the tie-breaker was unavailable.

    Regression companion to the looks_like_resume test above: proves the
    awaited tie-break path is event-loop safe (the old `asyncio.run` call
    crashed ambiguous uploads with HTTP 500 inside async routes).
    """
    is_friendly, reason = await is_ats_friendly(FLATTENED_PROSE_TEXT)
    assert is_friendly is True
    assert reason == ""


def test_extract_text_from_normal_pdf_is_readable():
    pdf_bytes = _build_pdf_with_positioned_words(
        [["Jane", "Doe"], ["Backend", "Engineer", "with", "6", "years", "experience."]]
    )
    result = extract_text(pdf_bytes, "resume.pdf", "application/pdf")
    assert result.warning is None
    assert "Jane Doe" in result.text
    assert "Backend Engineer" in result.text


async def test_extract_text_reconstructs_spaces_from_position_only_pdf():
    """Regression case: many LaTeX resume templates (Overleaf's Awesome-CV,
    Deedy-Resume, and similar) lay out justified text as individually
    positioned glyph runs with no literal space character between words —
    genuinely well-formatted resumes were extracting as unreadable
    run-together text ("JaneDoeBackendEngineerwith6yearsexperience") and
    failing the ATS-parsability gate through no fault of the candidate's.
    PyMuPDF reconstructs word boundaries from the actual glyph gaps; the
    previous pdfplumber-based extraction did not.
    """
    pdf_bytes = _build_pdf_with_positioned_words(
        [
            ["Jane", "Doe"],
            ["EXPERIENCE"],
            ["Backend", "Engineer", "with", "6", "years", "of", "experience."],
            ["Led", "the", "migration", "of", "the", "monolith", "to", "microservices."],
            ["EDUCATION"],
            ["B.S.", "Computer", "Science,", "State", "University,", "2019"],
            ["SKILLS"],
            ["Python,", "FastAPI,", "PostgreSQL,", "Docker,", "Kubernetes"],
        ]
    )
    result = extract_text(pdf_bytes, "resume.pdf", "application/pdf")
    # every word landed as its own glyph run with no space glyph anywhere —
    # a naive extractor would return "JaneDoe" / "BackendEngineerwith...".
    assert "JaneDoe" not in result.text
    assert "Backend Engineer with 6 years" in result.text

    verdict, reason = assess_parsability(result.text)
    assert verdict == "ok"
    assert reason == ""

    is_friendly, reason = await is_ats_friendly(result.text)
    assert is_friendly is True
    assert reason == ""
