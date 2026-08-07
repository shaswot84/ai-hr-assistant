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
    """Connection to PostgreSQL (asyncpg driver).

    The sync recruitment/auth engine (db/sync_session.py) derives its own
    +psycopg2 URL from this one at import time — see `_sync_url()` there.
    """

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

    top_k: int = 30  # candidates fetched per retrieval leg (BM25 / vector)
    rerank_top_n: int = 15  # chunks kept after reranking
    bm25_weight: float = 1.0  # RRF weight for the lexical (BM25) leg
    vector_weight: float = 1.0  # RRF weight for the semantic (vector) leg
    rrf_k: int = 60  # smoothing constant for Reciprocal Rank Fusion
    # bge-reranker scores are sigmoid-compressed; real hits cluster ~0.55-0.65
    # and weak matches ~0.5. Confidence is peak-anchored (see confidence.py).
    confidence_threshold: float = 0.55
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
    """Authentication provider selection (JWT is the only supported runtime provider)."""

    provider: str = "jwt"  # jwt

    model_config = SettingsConfigDict(env_prefix="AUTH_")


class JwtSettings(BaseSettings):
    """Self-issued JWT authentication — the single runtime auth provider.

    The backend signs short-lived HS256 access tokens after verifying email +
    password against the `application_user` table. No external IdP is involved,
    so every localhost/dev clone works identically with no cloud dependency.
    """

    secret_key: str = ""  # JWT_SECRET_KEY (HS256 signing secret; must be set in prod)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60  # short-lived; role re-read from DB per request
    issuer: str = "ai-hr-assistant"

    model_config = SettingsConfigDict(env_prefix="JWT_")


class MinioSettings(BaseSettings):
    """S3-compatible object storage for authoritative HR documents (resumes + ingestion uploads)."""

    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "hr-documents"
    secure: bool = False
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


class IngestionSettings(BaseSettings):
    """Ingestion pipeline knobs (worker + upload orchestration)."""

    poll_interval_seconds: float = 5.0
    max_file_size_bytes: int = 100 * 1024 * 1024
    max_pages: int = 500
    chunk_max_tokens: int = 500
    chunk_overlap_tokens: int = 50
    embed_batch_size: int = 32
    # Worker claims at most this many PENDING jobs per loop pass.
    max_jobs_per_pass: int = 8

    model_config = SettingsConfigDict(env_prefix="INGESTION_")


class OutputSafetySettings(BaseSettings):
    """Configuration for the Output Safety layer (final response guards).

    The deterministic guards (evidence, citations, PII, sensitive topics) run
    always when enabled; the LLM-as-judge verifier is optional.
    """

    enabled: bool = True
    require_citation: bool = True
    redact_pii: bool = True
    redaction_token: str = "[REDACTED]"
    judge_enabled: bool = False
    judge_model: str = "llama3.2"
    judge_timeout_seconds: float = 30.0
    sensitive_topics: list[str] = [
        "LEGAL_ADVICE",
        "TERMINATION_RECOMMENDATION",
        "COMPENSATION_DECISION",
    ]

    model_config = SettingsConfigDict(env_prefix="OUTPUT_SAFETY_")


class CorsSettings(BaseSettings):
    """CORS origins allowed to call the API from the browser.

    The Next.js frontend runs on a different origin (``localhost:3000``) and
    calls the API directly, so the API must send CORS headers. Comma-separated
    list; ``*`` (default) allows any origin — fine for local dev, since no
    cookies/credentials are used.
    """

    allow_origins: str = "*"

    model_config = SettingsConfigDict(env_prefix="CORS_")


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
    jwt: JwtSettings = JwtSettings()
    minio: MinioSettings = MinioSettings()
    smtp: SmtpSettings = SmtpSettings()
    chat: ChatSettings = ChatSettings()
    ingestion: IngestionSettings = IngestionSettings()
    output_safety: OutputSafetySettings = OutputSafetySettings()
    cors: CorsSettings = CorsSettings()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> AppSettings:
    """Return a cached singleton of the resolved settings."""
    return AppSettings()
