import asyncio
import math

from app.model_gateway.interfaces import Reranker


def sigmoid(logit: float) -> float:
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
        logits = await asyncio.to_thread(model.predict, inputs)
        return [sigmoid(float(score)) for score in logits]
