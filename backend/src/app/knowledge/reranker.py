"""Knowledge-side reranker wiring.

``PassThroughReranker`` is the model-free fallback used when reranking is
disabled; real models live in ``app.model_gateway``.
"""

from app.model_gateway.interfaces import Reranker


class PassThroughReranker(Reranker):
    """Identity reranker used when reranking is disabled.

    Keeps the pipeline intact without requiring a model, preserving the
    RRF ordering and normalizing to [0, 1].
    """

    model = "passthrough"

    async def rerank(self, query: str, pairs: list[tuple[str, str]]) -> list[float]:
        count = len(pairs)
        if count == 0:
            return []
        # Neutral score keeps ordering stable when no model is available.
        return [0.5] * count
