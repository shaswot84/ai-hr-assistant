import pytest

from app.config.settings import RetrievalSettings
from app.knowledge.ranking import reciprocal_rank_fusion


def test_rrf_combines_lists():
    result = dict(
        reciprocal_rank_fusion(
            ["a", "b", "c"],
            ["c", "a", "d"],
        )
    )
    assert result["a"] > result["c"] > result["b"] > result["d"]


def test_rrf_ranks_first_in_both_lists_highest():
    result = dict(reciprocal_rank_fusion(["x", "y"], ["x", "z"]))
    assert result["x"] == max(result.values())


def test_rrf_respects_custom_k():
    k = 60
    first = reciprocal_rank_fusion(["a", "b"], k=k)
    second = reciprocal_rank_fusion(["a", "b"], k=k)
    assert first == second
    assert first[0][1] == pytest.approx(1 / (k + 1))


def test_rrf_empty_inputs():
    assert reciprocal_rank_fusion() == []
    assert reciprocal_rank_fusion([], []) == []


def test_rrf_from_settings():
    settings = RetrievalSettings(rrf_k=10)
    result = dict(reciprocal_rank_fusion(["a"], ["a"], settings=settings))
    assert result["a"] == 2 / 11
