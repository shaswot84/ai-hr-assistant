"""Confidence estimation and the low-confidence gate for retrieval."""

import math

from app.config.settings import RetrievalSettings
from app.knowledge.contracts import RetrievedChunk


class ConfidenceEstimator:
    """Estimates retrieval confidence from reranker scores.

    Cross-encoder scores are sigmoid-compressed and cluster near 0.5 even
    for weak matches, so the mean over the top-N barely discriminates
    (junk and real hits both land ~0.5). Confidence is anchored to the
    best hit instead: ``0.75 * peak + 0.25 * runner_up``. The peak carries
    the real signal and the runner-up adds a small corroboration term, so
    one strong match reads clearly above neutral while ties stay near 0.5.
    When reranking is disabled (no reranker scores), confidence falls back
    to the same peak-anchored formula over retrieval (RRF) scores.
    """

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self._settings = settings or RetrievalSettings()

    def estimate(self, chunks: list[RetrievedChunk]) -> float:
        if not chunks:
            return 0.0

        reranker_scores = [c.reranker_score for c in chunks if c.reranker_score is not None]
        scores = reranker_scores or [c.retrieval_score for c in chunks]
        if not scores:
            return 0.0

        ordered = sorted(scores, reverse=True)
        peak = ordered[0]
        runner_up = ordered[1] if len(ordered) > 1 else peak
        return 0.75 * peak + 0.25 * runner_up


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
