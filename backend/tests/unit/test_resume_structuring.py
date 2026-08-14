from __future__ import annotations

import pytest

from app.evaluation.resume_structuring import (
    DEFAULT_SYSTEM_PROMPT,
    USER_PROMPT,
    WorkExperienceEntry,
    _compute_total_years,
    _is_current,
    _parse_education,
    _parse_work_experience,
    _parse_year,
    extract_structured_resume,
)
from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError


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


async def test_extract_structured_resume_raises_without_llm_configured():
    """No AI provider is configured in the test environment. There's no
    deterministic fallback anymore — a rough year-span guess with no
    titles/companies/degrees isn't an honest substitute for real extraction,
    so this must raise and let the caller record a failed evaluation.
    """
    text = "Jane Doe\nEXPERIENCE\nEngineer at Acme, 2019 to 2022\nEDUCATION\nB.S. CS, 2019"
    with pytest.raises(ChatProviderError):
        await extract_structured_resume(text)


async def test_extract_structured_resume_uses_default_prompts_when_none_given(monkeypatch):
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["system_prompt"] = system_prompt
        seen["user_prompt"] = user_prompt
        return {"workExperience": [], "education": [], "skills": []}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    await extract_structured_resume("Jane Doe resume text.", api_base="x", model="y", api_key="z")
    assert seen["system_prompt"] == DEFAULT_SYSTEM_PROMPT
    assert "Jane Doe resume text." in seen["user_prompt"]


async def test_extract_structured_resume_uses_manager_customised_prompts(monkeypatch):
    """A manager-edited system/user prompt must actually reach the LLM call."""
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["system_prompt"] = system_prompt
        seen["user_prompt"] = user_prompt
        return {"workExperience": [], "education": [], "skills": []}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    custom_system = "TEST-MARKER: extract only dates."
    custom_user = 'Return {"years": number} for: $resume_text'
    await extract_structured_resume(
        "Jane Doe resume text.",
        system_prompt=custom_system,
        user_prompt=custom_user,
        api_base="x",
        model="y",
        api_key="z",
    )
    assert seen["system_prompt"] == custom_system
    # str.format() would raise on the stray `{`/`}` above — string.Template must not.
    assert seen["user_prompt"] == 'Return {"years": number} for: Jane Doe resume text.'


def test_default_user_prompt_has_no_str_format_style_placeholders():
    """Regression guard: USER_PROMPT must use `string.Template` `$name`
    placeholders, not `{name}` — the template's JSON schema is full of
    literal braces that would collide with `.format()`."""
    assert "{resume_text}" not in USER_PROMPT
    assert "$resume_text" in USER_PROMPT
