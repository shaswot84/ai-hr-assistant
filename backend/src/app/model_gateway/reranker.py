"""In-process cross-encoder reranker for the Model Gateway."""

import asyncio
import math

from app.model_gateway.interfaces import Reranker


def sigmoid(logit: float) -> float:
    """Squash a raw cross-encoder logit into the [0, 1] score range.

    Uses a numerically stable formulation for large positive and negative
    inputs.
    """
    if logit >= 0:
        z = math.exp(-logit)
        return 1.0 / (1.0 + z)
    z = math.exp(logit)
    return z / (1.0 + z)


class SentenceTransformerReranker(Reranker):
    """Cross-encoder reranker loaded in-process via sentence-transformers.

    Runs ``BAAI/bge-reranker-base`` directly in the backend process (weights
    downloaded to the Hugging Face cache on first use). Predictions run in a
    thread to avoid blocking the event loop; raw logits are squashed to
    ``[0, 1]`` with sigmoid. Requires the optional ``reranker`` extra.
    """

    def __init__(
        self,
        model_name: str,
        *,
        version: str = "",
        device: str | None = None,
    ) -> None:
        self.model = model_name
        self.version = version
        self._device = device
        self._cross_encoder = None

    def _load(self):
        if self._cross_encoder is None:
            from sentence_transformers import CrossEncoder

            self._cross_encoder = CrossEncoder(self.model, device=self._device)
        return self._cross_encoder

    async def rerank(self, query: str, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        model = await asyncio.to_thread(self._load)
        inputs = [[query, document] for _, document in pairs]
        # CrossEncoder.predict applies sigmoid by default for single-label
        # models; request the raw logits (identity activation) so we apply
        # sigmoid exactly once here instead of twice.
        logits = await asyncio.to_thread(
            model.predict, inputs, activation_fn=lambda x: x
        )
        return [sigmoid(float(score)) for score in logits]
