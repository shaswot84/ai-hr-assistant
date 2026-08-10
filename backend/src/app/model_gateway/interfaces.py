"""Model Gateway interfaces: the abstraction for all AI model access.

Concrete adapters (Ollama, sentence-transformers, cloud providers, ...) live
in this package and implement these interfaces, keeping the rest of the app
decoupled from where models actually run.
"""

import abc
from collections.abc import AsyncIterator


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


class LLM(abc.ABC):
    """Generative LLM that produces the final, polished answer.

    Consumes grounded context (retrieved chunks) plus the user query and
    returns a natural-language answer. Concrete adapters (Ollama Cloud,
    OpenAI, ...) implement this interface behind the Model Gateway.
    """

    model: str = ""

    @abc.abstractmethod
    async def complete(self, system: str, user: str) -> str:
        """Return the model's completion for the given system/user messages."""
        raise NotImplementedError

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Yield the completion in chunks (token streaming).

        The default implementation buffers ``complete()`` into a single chunk,
        so adapters without native streaming still work; streaming-capable
        adapters (e.g. Ollama) override this with a true token stream.
        """
        yield await self.complete(system, user)
