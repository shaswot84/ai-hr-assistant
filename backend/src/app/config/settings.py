from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    debug: bool = True

    # auth
    auth_provider: str = "dev_stub"  # dev_stub | keycloak
    secret_key: str = "dev-secret-change-me"

    # database
    database_url: str = "postgresql+psycopg2://hr:hr-dev-password@postgres:5432/hr"

    # minio
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "hr-assets"
    minio_auto_init: bool = True  # ensure bucket exists on startup (disable in tests)

    # email / smtp (mailpit in dev)
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "AI HR Assistant <no-reply@hr.local>"

    # ai scoring (hosted ollama)
    ollama_api_base: str = "https://ollama.com"  # OpenAI-compatible base; provider appends /v1/chat/completions
    ollama_api_key: str = ""
    ollama_model: str = "gpt-oss:120b-cloud"  # must be a hosted Ollama cloud model
    ollama_request_timeout: float = 60.0

    # keycloak (only when auth_provider=keycloak)
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "hr-assistant"
    keycloak_client_id: str = "hr-portal"
    keycloak_client_secret: str = "change-me"
    keycloak_redirect_uri: str = "http://localhost:3000/auth/callback"

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
