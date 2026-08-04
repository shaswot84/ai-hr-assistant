"""Unit tests for the sentence-transformers reranker and sigmoid helper."""

import pytest

from app.model_gateway.reranker import SentenceTransformerReranker, sigmoid


@pytest.mark.parametrize(
    ("logit", "expected"),
    [(0.0, 0.5), (10.0, 1.0), (-10.0, 0.0), (1.0, 0.7310585786300049)],
)
def test_sigmoid(logit, expected):
    """Sigmoid maps 0 to 0.5 and approaches 0/1 at the extremes."""
    assert sigmoid(logit) == pytest.approx(expected, abs=1e-4)


@pytest.mark.asyncio
async def test_rerank_uses_cross_encoder_and_returns_scores(monkeypatch):
    """Scores are sigmoid-normalized and ordered consistently with logits."""
    reranker = SentenceTransformerReranker("fake/reranker", device="cpu")

    class FakeCrossEncoder:
        def predict(self, inputs):
            assert inputs == [["q", "doc1"], ["q", "doc2"]]
            return [2.0, -1.0]

    # Replace the lazy loader so no real model/torch is needed.
    monkeypatch.setattr(reranker, "_load", lambda: FakeCrossEncoder())

    scores = await reranker.rerank("q", [("q", "doc1"), ("q", "doc2")])

    assert len(scores) == 2
    assert 0.0 <= scores[0] <= 1.0
    assert scores[0] > scores[1]
    assert reranker.model == "fake/reranker"


@pytest.mark.asyncio
async def test_rerank_empty_pairs(monkeypatch):
    """No pairs short-circuits without ever loading the model."""
    reranker = SentenceTransformerReranker("fake/reranker")

    def fail_load():
        raise AssertionError("model should not load for empty input")

    monkeypatch.setattr(reranker, "_load", fail_load)

    assert await reranker.rerank("q", []) == []
