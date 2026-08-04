from collections import defaultdict
from collections.abc import Iterable

from app.config.settings import RetrievalSettings


def reciprocal_rank_fusion(
    *ranked_lists: Iterable[str],
    k: int | None = None,
    settings: RetrievalSettings | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked chunk-id lists using Reciprocal Rank Fusion.

    RRF assigns each item in a ranked list the contribution ``1 / (k + rank)``
    and sums contributions across all sources. Items ranked first in more
    lists score highest.
    """
    if k is None:
        k = settings.rrf_k if settings else 60

    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[str(item)] += 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
