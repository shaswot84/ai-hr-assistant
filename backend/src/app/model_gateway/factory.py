"""Wiring from settings to concrete Model Gateway adapters.

The deployment choice (Ollama HTTP vs. in-process vs. cloud) is decided here,
so callers depend only on the ``Embedder`` / ``Reranker`` interfaces.
"""

from app.config.settings import AppSettings, get_settings
from app.knowledge.reranker import PassThroughReranker
from app.model_gateway.embedder import OllamaEmbedder
from app.model_gateway.interfaces import Embedder, Reranker
from app.model_gateway.reranker import SentenceTransformerReranker


def build_embedder(settings: AppSettings | None = None) -> Embedder:
    """Build the embedding adapter from settings (Ollama by default)."""
    settings = settings or get_settings()
    return OllamaEmbedder(
        base_url=settings.model_gateway.url,
        model=settings.embedding.model,
        version=settings.embedding.version,
        dimension=settings.embedding.dimension,
        timeout_seconds=settings.model_gateway.timeout_seconds,
    )


def build_reranker(settings: AppSettings | None = None) -> Reranker:
    """Build the reranker, or pass-through when reranking is disabled."""
    settings = settings or get_settings()
    if not settings.reranker.enabled:
        return PassThroughReranker()
    return SentenceTransformerReranker(
        settings.reranker.model,
        version=settings.reranker.version,
    )
