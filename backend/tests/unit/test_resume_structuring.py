from __future__ import annotations

from app.evaluation.resume_structuring import (
    WorkExperienceEntry,
    _compute_total_years,
    _is_current,
    _parse_education,
    _parse_work_experience,
    _parse_year,
    extract_structured_resume,
)


def test_parse_year_extracts_four_digit_year():
    assert _parse_year("Jan 2021") == 2021
    assert _parse_year("2021") == 2021
    assert _parse_year("03/2021 - 05/2022") == 2021


def test_parse_year_returns_none_when_no_year_present():
    assert _parse_year("Present") is None
    assert _parse_year("") is None
    assert _parse_year(None) is None


def test_is_current_matches_common_phrasing():
    assert _is_current("Present") is True
    assert _is_current("current") is True
    assert _is_current("2024") is False
    assert _is_current("") is False


def test_compute_total_years_uses_career_span_not_summed_durations():
    """Two overlapping roles must not double-count — the span from the
    earliest start to the latest end is what gets reported, matching how
    "years of experience" is conventionally estimated.
    """
    entries = [
        WorkExperienceEntry(
            title="A", company="X", start_date="2019", end_date="2021",
            start_year=2019, end_year=2021,
        ),
        WorkExperienceEntry(
            title="B", company="Y", start_date="2020", end_date="2022",
            start_year=2020, end_year=2022,
        ),
    ]
    assert _compute_total_years(entries) == 3.0  # 2019 -> 2022, not 2+2=4


def test_compute_total_years_treats_current_role_as_ongoing():
    entries = [
        WorkExperienceEntry(
            title="A", company="X", start_date="2020", end_date="Present",
            start_year=2020, end_year=None, is_current=True,
        ),
    ]
    from datetime import UTC, datetime

    expected = datetime.now(UTC).year - 2020
    assert _compute_total_years(entries) == float(expected)


def test_compute_total_years_returns_zero_for_no_resolvable_dates():
    assert _compute_total_years([]) == 0.0
    entries = [WorkExperienceEntry(title="A", company="X", start_date="", end_date="")]
    assert _compute_total_years(entries) == 0.0


def test_parse_work_experience_from_llm_shaped_payload():
    raw = [
        {"title": "Senior Engineer", "company": "Acme", "startDate": "2021", "endDate": "Present"},
        {"title": "Engineer", "company": "Startup", "startDate": "2019", "endDate": "2021"},
    ]
    entries = _parse_work_experience(raw)
    assert len(entries) == 2
    assert entries[0].title == "Senior Engineer"
    assert entries[0].start_year == 2021
    assert entries[0].is_current is True
    assert entries[1].end_year == 2021


def test_parse_work_experience_ignores_malformed_entries():
    assert _parse_work_experience("not a list") == []
    assert _parse_work_experience([1, 2, "x"]) == []


def test_parse_education_from_llm_shaped_payload():
    raw = [{"degree": "B.S. Computer Science", "institution": "State University", "graduationYear": "2019"}]
    entries = _parse_education(raw)
    assert len(entries) == 1
    assert entries[0].graduation_year == 2019


async def test_extract_structured_resume_falls_back_without_llm_configured():
    """No AI provider is configured in the test environment, so this must
    use the deterministic fallback rather than raise or hang on a network call.
    """
    text = "Jane Doe\nEXPERIENCE\nEngineer at Acme, 2019 to 2022\nEDUCATION\nB.S. CS, 2019"
    result = await extract_structured_resume(text)
    assert result.model == "deterministic-fallback"
    assert result.work_experience == []
    assert result.education == []
    # crude fallback: earliest (2019) to latest (2022) year found anywhere in the text
    assert result.total_years_experience == 3.0


async def test_extract_structured_resume_fallback_handles_no_years_found():
    result = await extract_structured_resume("No dates here at all.")
    assert result.total_years_experience == 0.0
