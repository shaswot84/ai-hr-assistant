import abc


class Embedder(abc.ABC):
    """Embeds texts into dense vectors via the Model Gateway."""

    model: str = ""
    version: str = ""
    dimension: int = 0

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one normalized vector per input text."""
        raise NotImplementedError


class Reranker(abc.ABC):
    """Cross-encoder reranker accessed through the Model Gateway."""

    model: str = ""

    @abc.abstractmethod
    async def rerank(self, query: str, pairs: list[tuple[str, str]]) -> list[float]:
        """Return one relevance score in [0, 1] per ``(query, text)`` pair."""
        raise NotImplementedError
