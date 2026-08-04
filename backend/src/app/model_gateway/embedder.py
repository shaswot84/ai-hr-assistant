import math

import httpx

from app.model_gateway.interfaces import Embedder


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


class OllamaEmbedder(Embedder):
    """Embeds text by calling Ollama's ``/api/embed`` endpoint.

    The model weights live in Ollama's store (GGUF blobs); this client only
    talks HTTP. Embeddings are L2-normalized so cosine similarity at query
    time is consistent with the pgvector index.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        version: str = "",
        dimension: int = 768,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.version = version
        self.dimension = dimension
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds
        )

    async def embed(self, texts: list[str], *, prefix: str = "") -> list[list[float]]:
        prefixed = [f"{prefix}{text}" if prefix else text for text in texts]
        response = await self._client.post(
            "/api/embed", json={"model": self.model, "input": prefixed}
        )
        response.raise_for_status()
        payload = response.json()
        return [l2_normalize(list(embedding)) for embedding in payload["embeddings"]]

    async def aclose(self) -> None:
        await self._client.aclose()
