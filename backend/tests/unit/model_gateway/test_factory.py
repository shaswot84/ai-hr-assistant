"""Unit tests for Model Gateway wiring (build_embedder / build_reranker)."""

from app.config.settings import AppSettings, RerankerSettings
from app.knowledge.reranker import PassThroughReranker
from app.model_gateway import factory
from app.model_gateway.reranker import SentenceTransformerReranker


def _settings(enabled: bool) -> AppSettings:
    return AppSettings(reranker=RerankerSettings(enabled=enabled))


def test_build_reranker_disabled_returns_passthrough():
    assert isinstance(factory.build_reranker(_settings(enabled=False)), PassThroughReranker)


def test_build_reranker_enabled_missing_extra_degrades_loudly(monkeypatch, caplog):
    """Enabled but sentence-transformers absent -> pass-through + a warning."""
    monkeypatch.setattr(factory, "_reranker_available", lambda: False)
    reranker = factory.build_reranker(_settings(enabled=True))
    assert isinstance(reranker, PassThroughReranker)
    assert "sentence-transformers is not installed" in caplog.text


def test_build_reranker_enabled_returns_sentence_transformer(monkeypatch):
    monkeypatch.setattr(factory, "_reranker_available", lambda: True)
    reranker = factory.build_reranker(_settings(enabled=True))
    assert isinstance(reranker, SentenceTransformerReranker)
    assert reranker.model == "BAAI/bge-reranker-base"
