from __future__ import annotations

from app.knowledge.resume_extraction import looks_like_resume

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


def test_looks_like_resume_accepts_real_resume():
    is_resume, reason = looks_like_resume(REAL_RESUME_TEXT)
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
    """A long document with no resume signals (no contact info, no section
    keywords, no dates) should still be rejected even though it clears the
    minimum length bar — e.g. a random report or terms-of-service PDF.
    """
    unrelated = (
        "This quarterly report summarizes company performance across several "
        "business units and outlines strategic priorities for the coming period. "
    ) * 5
    is_resume, reason = looks_like_resume(unrelated)
    assert is_resume is False
    assert "doesn't look like a resume" in reason


def test_looks_like_resume_rejects_single_signal_document():
    """Contact info alone (e.g. a business card scan or email signature) isn't
    enough — needs at least two independent signals.
    """
    text = ("Jane Doe jane.doe@example.com Thank you for reaching out. " * 6)
    is_resume, reason = looks_like_resume(text)
    assert is_resume is False
    assert "doesn't look like a resume" in reason
