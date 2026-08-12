from __future__ import annotations

import pytest

from app.knowledge.resume_extraction import classify_resume, looks_like_resume

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


def test_looks_like_resume_accepts_real_resume():
    is_resume, reason = looks_like_resume(REAL_RESUME_TEXT)
    assert is_resume is True
    assert reason == ""


def test_looks_like_resume_accepts_short_resume_missing_contact_info():
    """Regression test: a real (if sparse) resume missing contact info must
    not be rejected just because one signal is absent.
    """
    is_resume, reason = looks_like_resume(SHORT_RESUME_NO_CONTACT)
    assert is_resume is True
    assert reason == ""


def test_looks_like_resume_accepts_resume_with_single_header_and_degree():
    """Only one explicit section header ("SKILLS"), but a degree phrase and
    a date make up for it — still confidently a resume.
    """
    text = """Alex Kim
SKILLS
Java, SQL, Project Management
Graduated from Boston University in 2020 with a Bachelor of Arts."""
    is_resume, reason = looks_like_resume(text)
    assert is_resume is True
    assert reason == ""


def test_looks_like_resume_rejects_blank_text():
    is_resume, reason = looks_like_resume("")
    assert is_resume is False
    assert "readable text" in reason


def test_looks_like_resume_rejects_short_text():
    is_resume, reason = looks_like_resume("Thanks for your time, see attached.")
    assert is_resume is False
    assert "readable text" in reason


def test_looks_like_resume_rejects_unrelated_long_document():
    """A long document with zero resume signals (no contact info, no section
    header lines, no degree phrasing, no dates, no line structure) is
    confidently rejected without needing an LLM call — e.g. a business report.
    """
    unrelated = (
        "This quarterly report summarizes company performance across several "
        "business units and outlines strategic priorities for the coming period. "
    ) * 5
    is_resume, reason = looks_like_resume(unrelated)
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


def test_looks_like_resume_fails_open_on_ambiguous_without_llm_configured():
    """No AI provider is configured in the test environment, so an ambiguous
    case must fail open (accept) rather than silently block a real candidate
    just because no tie-breaker was available.
    """
    text = "Jane Doe jane.doe@example.com Thank you for reaching out. " * 6
    is_resume, reason = looks_like_resume(text)
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
