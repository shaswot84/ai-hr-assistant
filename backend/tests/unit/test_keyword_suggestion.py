from __future__ import annotations

import pytest

from app.evaluation.keyword_suggestion import (
    DEFAULT_SYSTEM_PROMPT,
    TIER_WEIGHTS,
    SuggestedKeyword,
    _dedupe_keywords,
    _normalize_keyword,
    _normalize_tier,
    suggest_keywords,
)
from app.model_gateway.ollama import OllamaChatProvider
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


async def test_suggest_keywords_uses_default_system_prompt_when_none_given(monkeypatch):
    """No override configured (the common case) falls back to DEFAULT_SYSTEM_PROMPT."""
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["system_prompt"] = system_prompt
        return {"keywords": [{"keyword": "python", "tier": "critical"}]}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    await suggest_keywords(
        "Backend Engineer", "Python developer.", api_base="x", model="y", api_key="z"
    )
    assert seen["system_prompt"] == DEFAULT_SYSTEM_PROMPT


async def test_suggest_keywords_uses_manager_customised_system_prompt(monkeypatch):
    """A manager-edited prompt (via Settings) must actually reach the LLM call,
    not just be stored — this is the whole point of it being configurable."""
    seen = {}

    async def fake_complete_json(self, *, system_prompt, user_prompt):
        seen["system_prompt"] = system_prompt
        return {"keywords": []}

    monkeypatch.setattr(OllamaChatProvider, "is_configured", lambda self: True)
    monkeypatch.setattr(OllamaChatProvider, "complete_json", fake_complete_json)

    custom_prompt = "Only extract keywords explicitly listed under 'Requirements:'."
    await suggest_keywords(
        "Backend Engineer",
        "Python developer.",
        api_base="x",
        model="y",
        api_key="z",
        system_prompt=custom_prompt,
    )
    assert seen["system_prompt"] == custom_prompt
