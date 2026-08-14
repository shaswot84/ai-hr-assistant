from __future__ import annotations

import pytest

from app.evaluation.resume_structuring import StructuredResume, WorkExperienceEntry
from app.evaluation.scoring import (
    DEFAULT_RECOMMENDATION,
    DEFAULT_SYSTEM_PROMPT,
    DOES_NOT_MEET_REQUIREMENTS,
    USER_PROMPT,
    _apply_deterministic_requirement_checks,
    _compute_keyword_score,
    _normalize_review,
    _reconcile_keyword_matches_with_taxonomy,
    _reconcile_keywords_with_taxonomy,
    _requirements,
    score_resume,
)
from app.model_gateway.ollama import OllamaChatProvider
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


async def test_score_resume_uses_default_prompts_when_none_given(monkeypatch):
    """No manager override configured (the common case) falls back to the
    built-in system/user prompt constants."""
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["system_prompt"] = system_prompt
        seen["user_prompt"] = user_prompt
        return {"summary": "ok"}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    await score_resume(
        resume_text="Python developer.",
        job_title="Backend Engineer",
        job_description="Need Python.",
        api_base="x",
        model="y",
        api_key="z",
    )
    assert seen["system_prompt"] == DEFAULT_SYSTEM_PROMPT
    assert "Backend Engineer" in seen["user_prompt"]
    assert "Python developer." in seen["user_prompt"]


async def test_score_resume_uses_manager_customised_prompts(monkeypatch):
    """A manager-edited system/user prompt (via Settings) must actually reach
    the LLM call, not just be stored — this is the whole point of it being
    configurable."""
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["system_prompt"] = system_prompt
        seen["user_prompt"] = user_prompt
        return {"summary": "ok"}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    custom_system = "TEST-MARKER: only judge Python skills."
    custom_user = "Custom task for $job_title: $resume_text"
    await score_resume(
        resume_text="Python developer.",
        job_title="Backend Engineer",
        job_description="Need Python.",
        system_prompt=custom_system,
        user_prompt=custom_user,
        api_base="x",
        model="y",
        api_key="z",
    )
    assert seen["system_prompt"] == custom_system
    assert seen["user_prompt"] == "Custom task for Backend Engineer: Python developer."


async def test_score_resume_user_prompt_survives_stray_braces(monkeypatch):
    """The task template is manager-editable and full of literal JSON braces
    (the response schema) — substitution must be brace-safe (string.Template,
    not str.format), so an edited template with unescaped `{`/`}` doesn't
    crash the whole evaluation.
    """
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["user_prompt"] = user_prompt
        return {"summary": "ok"}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    # Deliberately unescaped, unmatched braces plus an unknown $placeholder —
    # str.format() would raise on this; safe_substitute must not.
    custom_user = 'Return {"score": number} for $resume_text. Unknown: $not_a_real_placeholder'
    await score_resume(
        resume_text="Python developer.",
        job_title="Backend Engineer",
        job_description="Need Python.",
        user_prompt=custom_user,
        api_base="x",
        model="y",
        api_key="z",
    )
    assert '{"score": number}' in seen["user_prompt"]
    assert "Python developer." in seen["user_prompt"]
    assert "$not_a_real_placeholder" in seen["user_prompt"]


def test_default_user_prompt_has_no_str_format_style_placeholders():
    """Regression guard: the shipped USER_PROMPT constant must use
    `string.Template` `$name` placeholders, not `{name}` — otherwise the raw
    JSON-schema braces in the template would collide with `.format()`.
    """
    assert "{job_title}" not in USER_PROMPT
    assert "$job_title" in USER_PROMPT


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


# ── Weighted keyword scoring ────────────────────────────────────────────

SCORING_KEYWORDS = [
    {"keyword": "python", "tier": "critical"},
    {"keyword": "docker", "tier": "important"},
    {"keyword": "graphql", "tier": "nice_to_have"},
]


def test_compute_keyword_score_returns_none_without_scoring_keywords():
    """A vacancy with no configured keywords has nothing to compute a score
    from — None, not zero, since zero would misleadingly read as 'scored
    and failed' rather than 'not scored at all'.
    """
    assert _compute_keyword_score([{"keyword": "python", "present": True, "evidence": ""}], None) is None
    assert _compute_keyword_score([], []) is None


def test_compute_keyword_score_weights_by_tier():
    """Regression case for the core ask: the score is a fixed formula over
    tier weights (critical=5, important=3, nice_to_have=1), not anything
    the model invents. Python (critical, matched) + Docker (important,
    missing) + GraphQL (nice_to_have, not mentioned at all) -> 5 of 9.
    """
    matches = [
        {"keyword": "python", "present": True, "evidence": "Listed in skills."},
        {"keyword": "docker", "present": False, "evidence": "Not mentioned."},
        # graphql absent from the model's response entirely — must still count
        # against the total, not be silently skipped.
    ]
    score = _compute_keyword_score(matches, SCORING_KEYWORDS)
    assert score == round(100 * 5 / 9)


def test_compute_keyword_score_full_match_is_100():
    matches = [
        {"keyword": kw["keyword"], "present": True, "evidence": ""} for kw in SCORING_KEYWORDS
    ]
    assert _compute_keyword_score(matches, SCORING_KEYWORDS) == 100


def test_compute_keyword_score_no_match_is_zero():
    matches = [
        {"keyword": kw["keyword"], "present": False, "evidence": ""} for kw in SCORING_KEYWORDS
    ]
    assert _compute_keyword_score(matches, SCORING_KEYWORDS) == 0


def test_reconcile_keyword_matches_promotes_taxonomy_alias():
    """Same reasoning as the matched/missing keyword reconciliation: the
    model says 'Kubernetes' is absent, but the resume only spells it 'K8s'.
    Since this directly feeds the deterministic score, the override must
    actually flip `present`, not just relabel a display string.
    """
    matches = [{"keyword": "Kubernetes", "present": False, "evidence": "Not mentioned."}]
    reconciled = _reconcile_keyword_matches_with_taxonomy(matches, "Experienced with K8s in production.")
    assert reconciled[0]["present"] is True


def test_reconcile_keyword_matches_leaves_true_positive_missing_alone():
    matches = [{"keyword": "Kubernetes", "present": False, "evidence": "Not mentioned."}]
    reconciled = _reconcile_keyword_matches_with_taxonomy(matches, "Experienced with Python only.")
    assert reconciled[0]["present"] is False


def test_normalize_review_computes_keyword_score_end_to_end():
    data = {
        "recommendation": "Good Match",
        "keywordMatches": [
            {"keyword": "python", "present": True, "evidence": "Listed in skills."},
            {"keyword": "docker", "present": True, "evidence": "Mentioned in experience."},
            {"keyword": "graphql", "present": False, "evidence": "Not mentioned."},
        ],
    }
    review = _normalize_review(data, resume_text="Python and Docker experience.", scoring_keywords=SCORING_KEYWORDS)
    assert review["keywordScore"] == round(100 * 8 / 9)  # critical + important matched, nice_to_have missed
    assert review["keywordMatches"][0]["keyword"] == "python"


def test_normalize_review_keyword_score_is_none_without_scoring_keywords():
    """No scoring_keywords configured on the vacancy -> no score, even if the
    model payload happens to contain a keywordMatches list (shouldn't
    happen since the prompt only asks for it when keywords are given, but
    the None-vacancy-config case must win regardless).
    """
    data = {"recommendation": "Good Match", "keywordMatches": [{"keyword": "python", "present": True, "evidence": ""}]}
    review = _normalize_review(data, resume_text="Python experience.", scoring_keywords=None)
    assert review["keywordScore"] is None
