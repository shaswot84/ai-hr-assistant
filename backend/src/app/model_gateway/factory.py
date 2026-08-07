"""Wiring from settings to concrete Model Gateway adapters.

The deployment choice (Ollama HTTP vs. in-process vs. cloud) is decided here,
so callers depend only on the ``Embedder`` / ``Reranker`` interfaces.
"""

import logging

from app.config.settings import AppSettings, get_settings
from app.knowledge.reranker import PassThroughReranker
from app.model_gateway.embedder import OllamaEmbedder
from app.model_gateway.interfaces import Embedder, Reranker
from app.model_gateway.reranker import SentenceTransformerReranker

logger = logging.getLogger(__name__)


def _reranker_available() -> bool:
    """True when the optional ``reranker`` extra (sentence-transformers) is installed."""
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


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
    """Build the reranker, or pass-through when reranking is disabled.

    When reranking is enabled but the optional ``reranker`` extra is not
    installed, log a loud warning and fall back to pass-through so search
    keeps working. The degradation is visible in the logs — it is never a
    silent flat-0.5 score.
    """
    settings = settings or get_settings()
    if not settings.reranker.enabled:
        return PassThroughReranker()
    if not _reranker_available():
        logger.warning(
            "RERANKER_ENABLED=true but sentence-transformers is not installed; "
            "install the reranker extra (pip install '.[reranker]') and rebuild. "
            "Falling back to pass-through reranking."
        )
        return PassThroughReranker()
    return SentenceTransformerReranker(
        settings.reranker.model,
        version=settings.reranker.version,
    )
