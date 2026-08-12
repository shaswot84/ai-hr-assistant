from __future__ import annotations

import pytest

from app.evaluation.resume_structuring import StructuredResume, WorkExperienceEntry
from app.evaluation.scoring import (
    DEFAULT_RECOMMENDATION,
    DOES_NOT_MEET_REQUIREMENTS,
    _apply_deterministic_requirement_checks,
    _normalize_review,
    _reconcile_keywords_with_taxonomy,
    _requirements,
    score_resume,
)
from app.model_gateway.provider import ChatProviderError


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
    requirement must be flagged distinctly, not just given a positive label
    — even if the model itself reported "Strong Match".
    """
    data = {
        "requirements": [{"requirement": "5+ years of experience", "met": False, "evidence": "only 2 years"}],
        "recommendation": "Strong Match",
    }
    review = _normalize_review(data)
    assert review["requirementsMet"] is False
    assert review["recommendation"] == DOES_NOT_MEET_REQUIREMENTS


def test_normalize_review_keeps_recommendation_when_all_requirements_met():
    data = {
        "requirements": [{"requirement": "3+ years of experience", "met": True, "evidence": "5 years listed"}],
        "recommendation": "Strong Match",
    }
    review = _normalize_review(data)
    assert review["requirementsMet"] is True
    assert review["recommendation"] == "Strong Match"


def test_normalize_review_defaults_to_met_when_no_requirements_stated():
    data = {"recommendation": "Good Match"}
    review = _normalize_review(data)
    assert review["requirements"] == []
    assert review["requirementsMet"] is True
    assert review["recommendation"] == "Good Match"


def test_normalize_review_defaults_recommendation_when_model_omits_it():
    review = _normalize_review({})
    assert review["recommendation"] == DEFAULT_RECOMMENDATION


def test_normalize_review_applies_deterministic_override_when_structured_given():
    data = {
        "requirements": [{"requirement": "10+ years of experience", "met": True, "evidence": "seems senior"}],
        "recommendation": "Strong Match",
    }
    review = _normalize_review(data, _structured_with_years(2))
    assert review["requirements"][0]["met"] is False
    assert review["requirementsMet"] is False
    assert review["recommendation"] == DOES_NOT_MEET_REQUIREMENTS


def test_normalize_review_has_no_numeric_score_fields():
    """Regression case: there must be no headline or per-factor number left
    anywhere in the normalized payload — see the module docstring rationale.
    """
    data = {
        "recommendation": "Strong Match",
        "keyFactors": [{"factor": "Skills Match", "note": "Has all required technologies"}],
    }
    review = _normalize_review(data)
    assert "matchScore" not in review
    assert "score" not in review
    assert review["keyFactors"] == [{"factor": "Skills Match", "note": "Has all required technologies"}]


async def test_score_resume_raises_when_no_provider_configured():
    """No deterministic fallback anymore — an unconfigured provider must
    raise so the caller can record a failed evaluation instead of a
    fabricated keyword-overlap guess.
    """
    with pytest.raises(ChatProviderError):
        await score_resume(
            resume_text="Python developer with FastAPI experience.",
            job_title="Backend Engineer",
            job_description="Need Python and FastAPI skills.",
            api_base=None,
            model=None,
            api_key=None,
        )


def test_reconcile_keywords_moves_taxonomy_recognized_alias_from_missing_to_matched():
    """Regression case for the core ask: the model said 'Kubernetes' was
    missing, but the resume says 'K8s' — same skill, different spelling.
    """
    matched, missing = _reconcile_keywords_with_taxonomy(
        matched=["Python"],
        missing=["Kubernetes", "Some Unrelated Thing"],
        resume_text="Experienced with Python and K8s in production.",
    )
    assert "Kubernetes" in matched
    assert "Kubernetes" not in missing
    assert "Some Unrelated Thing" in missing  # not in the taxonomy, left untouched


def test_reconcile_keywords_leaves_missing_when_alias_truly_absent():
    matched, missing = _reconcile_keywords_with_taxonomy(
        matched=[], missing=["Kubernetes"], resume_text="Experienced with Python only.",
    )
    assert missing == ["Kubernetes"]
    assert matched == []


def test_normalize_review_reconciles_missing_keyword_using_resume_text():
    data = {
        "recommendation": "Good Match",
        "matchedKeywords": ["Python"],
        "missingKeywords": ["Kubernetes"],
    }
    review = _normalize_review(data, structured=None, resume_text="Deployed services on K8s using Python.")
    assert "Kubernetes" in review["matchedKeywords"]
    assert "Kubernetes" not in review["missingKeywords"]
