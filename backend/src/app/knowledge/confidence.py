"""Confidence estimation and the low-confidence gate for retrieval."""

import math

from app.config.settings import RetrievalSettings
from app.knowledge.contracts import RetrievedChunk


class ConfidenceEstimator:
    """Estimates retrieval confidence from reranker scores.

    Confidence is the mean reranker score over the top-N reranked chunks.
    When reranking is disabled (no reranker scores), confidence falls back
    to the mean normalized RRF score.
    """

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self._settings = settings or RetrievalSettings()

    def estimate(self, chunks: list[RetrievedChunk]) -> float:
        if not chunks:
            return 0.0

        reranker_scores = [c.reranker_score for c in chunks if c.reranker_score is not None]
        if reranker_scores:
            return sum(reranker_scores) / len(reranker_scores)

        return sum(c.retrieval_score for c in chunks) / len(chunks)


class LowConfidenceDetector:
    """Decides whether retrieval evidence is strong enough to answer."""

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self._settings = settings or RetrievalSettings()

    def is_low(self, confidence: float, chunk_count: int) -> bool:
        if chunk_count < self._settings.min_sources:
            return True
        return confidence < self._settings.confidence_threshold


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.fsum(values) / len(values)
