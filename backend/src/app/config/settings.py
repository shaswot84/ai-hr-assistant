"""Environment-driven application configuration.

Every setting group reads from environment variables (prefix below) and can
be overridden through a root `.env` file. Defaults keep a local dev setup
working out of the box.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Connection to PostgreSQL (asyncpg driver)."""

    url: str = "postgresql+asyncpg://hr:hr@localhost:5432/hr_assistant"
    echo: bool = False

    model_config = SettingsConfigDict(env_prefix="DATABASE_")


class EmbeddingSettings(BaseSettings):
    """Embedding model metadata; stored per-chunk for provenance/rebuilds."""

    model: str = "nomic-embed-text"
    version: str = "1.5"
    dimension: int = 768
    chunking_strategy: str = "structure_aware_v1"
    pipeline_version: str = "1.0.0"

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")


class RetrievalSettings(BaseSettings):
    """Query-time knobs for the hybrid retrieval pipeline."""

    top_k: int = 20  # candidates fetched per retrieval leg (BM25 / vector)
    rerank_top_n: int = 5  # chunks kept after reranking
    bm25_weight: float = 1.0
    vector_weight: float = 1.0
    rrf_k: int = 60  # smoothing constant for Reciprocal Rank Fusion
    confidence_threshold: float = 0.5
    min_sources: int = 1
    model_config = SettingsConfigDict(env_prefix="RETRIEVAL_")


class RerankerSettings(BaseSettings):
    """In-process cross-encoder reranker (optional)."""

    model: str = "BAAI/bge-reranker-base"
    enabled: bool = False
    version: str = "1.0"

    model_config = SettingsConfigDict(env_prefix="RERANKER_")


class ModelGatewaySettings(BaseSettings):
    """Connection to the local model runner (Ollama) for embeddings."""

    url: str = "http://localhost:11434"
    timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(env_prefix="OLLAMA_")


class AppSettings(BaseSettings):
    """Top-level settings: aggregates all groups and global flags."""

    app_env: str = "development"
    debug: bool = True

    database: DatabaseSettings = DatabaseSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    reranker: RerankerSettings = RerankerSettings()
    model_gateway: ModelGatewaySettings = ModelGatewaySettings()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> AppSettings:
    """Return a cached singleton of the resolved settings."""
    return AppSettings()
