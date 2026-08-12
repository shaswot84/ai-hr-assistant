from __future__ import annotations

from app.evaluation.resume_structuring import StructuredResume, WorkExperienceEntry
from app.evaluation.scoring import (
    DOES_NOT_MEET_REQUIREMENTS,
    _apply_deterministic_requirement_checks,
    _normalize_review,
    _requirements,
    _score_deterministic,
)


def _structured_with_years(years: float) -> StructuredResume:
    return StructuredResume(
        work_experience=[
            WorkExperienceEntry(
                title="Engineer", company="Acme", start_date="2020", end_date="Present",
                start_year=2020, end_year=None, is_current=True,
            )
        ],
        education=[],
        skills=[],
        total_years_experience=years,
        model="test",
    )


def test_requirements_parses_llm_shaped_payload():
    raw = [
        {"requirement": "3+ years of Python", "met": True, "evidence": "5 years listed"},
        {"requirement": "Bachelor's degree", "met": False, "evidence": "No degree found"},
    ]
    parsed = _requirements(raw)
    assert len(parsed) == 2
    assert parsed[0]["met"] is True
    assert parsed[1]["met"] is False


def test_requirements_ignores_malformed_entries():
    assert _requirements("not a list") == []
    assert _requirements([1, {"requirement": ""}, {"met": True}]) == []


def test_deterministic_requirement_check_overrides_llm_verdict_with_verified_years():
    """The LLM incorrectly says the 5-year requirement is met, but the
    verified structured data says only 3 years — the deterministic check
    must win, exactly like resume_structuring's own years calculation.
    """
    requirements = [{"requirement": "5+ years of experience", "met": True, "evidence": "looks senior"}]
    result = _apply_deterministic_requirement_checks(requirements, _structured_with_years(3))
    assert result[0]["met"] is False
    assert "Verified: 3" in result[0]["evidence"]


def test_deterministic_requirement_check_confirms_when_years_actually_met():
    requirements = [{"requirement": "3+ years of experience", "met": False, "evidence": "unclear"}]
    result = _apply_deterministic_requirement_checks(requirements, _structured_with_years(5))
    assert result[0]["met"] is True


def test_deterministic_requirement_check_leaves_non_numeric_requirements_alone():
    requirements = [{"requirement": "Must have a valid driver's license", "met": True, "evidence": "stated on resume"}]
    result = _apply_deterministic_requirement_checks(requirements, _structured_with_years(5))
    assert result[0]["met"] is True
    assert result[0]["evidence"] == "stated on resume"


def test_deterministic_requirement_check_noop_without_structured_data():
    requirements = [{"requirement": "5+ years of experience", "met": True, "evidence": "x"}]
    result = _apply_deterministic_requirement_checks(requirements, None)
    assert result[0]["met"] is True  # unchanged, no structured data to check against


def test_normalize_review_forces_recommendation_when_a_requirement_is_unmet():
    """Regression case for the core ask: a candidate failing a hard
    requirement must be flagged distinctly, not just scored low — even if
    the model itself reported a high matchScore and a positive label.
    """
    data = {
        "requirements": [{"requirement": "5+ years of experience", "met": False, "evidence": "only 2 years"}],
        "matchScore": 85,
        "recommendation": "Strong Match",
    }
    review = _normalize_review(data)
    assert review["requirementsMet"] is False
    assert review["recommendation"] == DOES_NOT_MEET_REQUIREMENTS
    assert review["matchScore"] == 85  # the numeric score is preserved, just not the label


def test_normalize_review_keeps_recommendation_when_all_requirements_met():
    data = {
        "requirements": [{"requirement": "3+ years of experience", "met": True, "evidence": "5 years listed"}],
        "matchScore": 90,
        "recommendation": "Strong Match",
    }
    review = _normalize_review(data)
    assert review["requirementsMet"] is True
    assert review["recommendation"] == "Strong Match"


def test_normalize_review_defaults_to_met_when_no_requirements_stated():
    data = {"matchScore": 70, "recommendation": "Good Match"}
    review = _normalize_review(data)
    assert review["requirements"] == []
    assert review["requirementsMet"] is True
    assert review["recommendation"] == "Good Match"


def test_normalize_review_applies_deterministic_override_when_structured_given():
    data = {
        "requirements": [{"requirement": "10+ years of experience", "met": True, "evidence": "seems senior"}],
        "matchScore": 95,
        "recommendation": "Strong Match",
    }
    review = _normalize_review(data, _structured_with_years(2))
    assert review["requirements"][0]["met"] is False
    assert review["requirementsMet"] is False
    assert review["recommendation"] == DOES_NOT_MEET_REQUIREMENTS


def test_score_deterministic_includes_requirements_fields_for_schema_consistency():
    """Even the no-LLM fallback path must carry requirements/requirementsMet
    so API consumers always find these keys, whichever path produced them.
    """
    result = _score_deterministic("Python developer with FastAPI experience.", "Backend Engineer", "Need Python and FastAPI skills.")
    assert result.raw_payload["requirements"] == []
    assert result.raw_payload["requirementsMet"] is True
