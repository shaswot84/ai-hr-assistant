"""Environment-driven application configuration.

Every setting group reads from environment variables (prefix below) and can
be overridden through a root `.env` file. Defaults keep a local dev setup
working out of the box.

Top-level settings aggregate the retrieval/embedding stack (shared with the
Knowledge Service) and the HR recruitment stack (auth, MinIO, email, and the
hosted Ollama chat API used for resume scoring).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Connection to PostgreSQL."""

    url: str = "postgresql+psycopg2://hr:hr@localhost:5432/hr_assistant"
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


class AuthSettings(BaseSettings):
    """Authentication provider selection and shared secrets."""

    provider: str = "dev_stub"  # dev_stub | keycloak
    secret_key: str = "dev-secret-change-me"

    model_config = SettingsConfigDict(env_prefix="AUTH_")


class KeycloakSettings(BaseSettings):
    """Keycloak OIDC realm configuration (used only when auth provider is keycloak)."""

    url: str = "http://localhost:8080"
    realm: str = "hr-assistant"
    client_id: str = "hr-portal"
    client_secret: str = "change-me"
    redirect_uri: str = "http://localhost:3000/auth/callback"

    model_config = SettingsConfigDict(env_prefix="KEYCLOAK_")

    @property
    def issuer(self) -> str:
        """Keycloak OIDC issuer URL, derived from url + realm."""
        return f"{self.url}/realms/{self.realm}"


class MinioSettings(BaseSettings):
    """S3-compatible object store (MinIO in dev). Authoritative bytes for resumes."""

    endpoint: str = "minio:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    secure: bool = False
    bucket: str = "hr-assets"
    auto_init: bool = True  # ensure bucket exists on startup (disable in tests)

    model_config = SettingsConfigDict(env_prefix="MINIO_")


class SmtpSettings(BaseSettings):
    """Outbound email (Mailpit in dev, SMTP/SES in prod)."""

    host: str = "mailpit"
    port: int = 1025
    user: str = ""
    password: str = ""
    from_addr: str = "AI HR Assistant <no-reply@hr.local>"

    model_config = SettingsConfigDict(env_prefix="SMTP_")


class ChatSettings(BaseSettings):
    """Hosted Ollama chat API used for AI resume scoring."""

    api_base: str = "https://ollama.com"  # OpenAI-compatible base; provider appends /v1/chat/completions
    api_key: str = ""
    model: str = "gpt-oss:120b-cloud"  # must be a hosted Ollama cloud model
    request_timeout: float = 60.0

    model_config = SettingsConfigDict(env_prefix="OLLAMA_CHAT_")


class AppSettings(BaseSettings):
    """Top-level settings: aggregates all groups and global flags."""

    app_env: str = "development"
    debug: bool = True

    database: DatabaseSettings = DatabaseSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    reranker: RerankerSettings = RerankerSettings()
    model_gateway: ModelGatewaySettings = ModelGatewaySettings()
    auth: AuthSettings = AuthSettings()
    keycloak: KeycloakSettings = KeycloakSettings()
    minio: MinioSettings = MinioSettings()
    smtp: SmtpSettings = SmtpSettings()
    chat: ChatSettings = ChatSettings()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> AppSettings:
    """Return a cached singleton of the resolved settings."""
    return AppSettings()