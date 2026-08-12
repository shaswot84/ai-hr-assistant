from __future__ import annotations

import pytest

from app.evaluation.keyword_suggestion import (
    TIER_WEIGHTS,
    SuggestedKeyword,
    _dedupe_keywords,
    _normalize_keyword,
    _normalize_tier,
    suggest_keywords,
)
from app.model_gateway.provider import ChatProviderError


def test_tier_weights_are_strictly_descending():
    """Critical must outweigh important must outweigh nice_to_have — the
    whole point of tiers is that a manager's 'this matters more' choice
    actually changes the score.
    """
    assert TIER_WEIGHTS["critical"] > TIER_WEIGHTS["important"] > TIER_WEIGHTS["nice_to_have"]


def test_normalize_tier_accepts_valid_values():
    assert _normalize_tier("critical") == "critical"
    assert _normalize_tier("important") == "important"
    assert _normalize_tier("nice_to_have") == "nice_to_have"


def test_normalize_tier_defaults_odd_values_to_important():
    """The manager reviews and can change every tier before posting, so an
    odd/missing tier from the model just needs a safe, unsurprising
    default — not perfect judgment.
    """
    assert _normalize_tier("urgent") == "important"
    assert _normalize_tier(None) == "important"
    assert _normalize_tier(123) == "important"


def test_normalize_keyword_canonicalizes_known_skill_alias():
    """A model-suggested 'K8s' should read as 'kubernetes' — the same
    canonical spelling the resume-side matching already looks for.
    """
    assert _normalize_keyword("K8s") == "kubernetes"
    assert _normalize_keyword("Js") == "javascript"


def test_normalize_keyword_leaves_unrecognized_terms_as_is():
    assert _normalize_keyword("Six Sigma Certification") == "Six Sigma Certification"


def test_dedupe_keywords_keeps_first_occurrence():
    """Sorting by tier (critical first) happens before dedup, so if the
    model suggests the same skill twice at different tiers, the
    higher-tier one survives.
    """
    keywords = [
        SuggestedKeyword(keyword="python", tier="critical"),
        SuggestedKeyword(keyword="python", tier="nice_to_have"),
        SuggestedKeyword(keyword="docker", tier="important"),
    ]
    deduped = _dedupe_keywords(keywords)
    assert len(deduped) == 2
    assert deduped[0].tier == "critical"


async def test_suggest_keywords_raises_when_no_provider_configured():
    """No deterministic fallback — a keyword list a manager can't trust the
    source of isn't worth generating silently.
    """
    with pytest.raises(ChatProviderError):
        await suggest_keywords(
            "Backend Engineer",
            "Looking for a Python developer with FastAPI experience.",
            api_base=None,
            model=None,
            api_key=None,
        )
