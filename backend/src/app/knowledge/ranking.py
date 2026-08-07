"""Rank fusion: merge multiple ranked lists into one consensus ranking."""

from collections import defaultdict
from collections.abc import Iterable

from app.config.settings import RetrievalSettings


def reciprocal_rank_fusion(
    *ranked_lists: Iterable[str],
    k: int | None = None,
    settings: RetrievalSettings | None = None,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked chunk-id lists using Reciprocal Rank Fusion.

    RRF assigns each item in a ranked list the contribution ``weight /
    (k + rank)`` and sums contributions across all sources. Items ranked
    first in more lists score highest; ``weights`` rebalances the relative
    influence of each list (default: all lists equal).
    """
    if k is None:
        k = settings.rrf_k if settings else 60
    if weights is None:
        if settings is not None:
            weights = [settings.bm25_weight, settings.vector_weight]
        else:
            weights = [1.0] * len(ranked_lists)
    # Tolerate a weight count that does not match the list count.
    weights = list(weights) + [1.0] * max(0, len(ranked_lists) - len(weights))
    weights = weights[: len(ranked_lists)]

    scores: dict[str, float] = defaultdict(float)
    for weight, ranked in zip(weights, ranked_lists, strict=True):
        for rank, item in enumerate(ranked, start=1):
            scores[str(item)] += weight / (k + rank)

    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
