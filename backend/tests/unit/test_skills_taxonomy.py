from __future__ import annotations

from app.evaluation.skills_taxonomy import find_skills_in_text, normalize_skill


def test_normalize_skill_recognizes_canonical_and_alias_case_insensitive():
    assert normalize_skill("Kubernetes") == "kubernetes"
    assert normalize_skill("k8s") == "kubernetes"
    assert normalize_skill("K8S") == "kubernetes"


def test_normalize_skill_returns_none_for_unrecognized_text():
    assert normalize_skill("underwater basket weaving") is None
    assert normalize_skill("") is None


def test_find_skills_in_text_matches_alias_not_just_canonical_spelling():
    text = "Managed clusters on K8s and deployed with Docker."
    found = find_skills_in_text(text)
    assert "kubernetes" in found
    assert "docker" in found


def test_find_skills_in_text_respects_word_boundaries():
    """'js' must not match inside unrelated words like 'objects' or 'jsdom'."""
    text = "Worked with data objects and jsdom-based testing utilities."
    found = find_skills_in_text(text)
    assert "javascript" not in found


def test_find_skills_in_text_handles_symbol_containing_terms():
    text = "Proficient in C++ and C# for systems programming."
    found = find_skills_in_text(text)
    assert "c++" in found
    assert "c#" in found


def test_find_skills_in_text_matches_multi_word_phrases():
    text = "5 years of experience in machine learning and project management."
    found = find_skills_in_text(text)
    assert "machine learning" in found
    assert "project management" in found


def test_find_skills_in_text_returns_empty_set_for_no_matches():
    assert find_skills_in_text("A completely unrelated sentence about gardening.") == set()
