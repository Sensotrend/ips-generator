"""Application settings, read from environment variables only (never from files in the repo)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Every field maps to the upper-case env var of the same name."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    app_env: str = "development"
    log_level: str = "INFO"

    # Anthropic. No default: must come from the environment when LLM steps run.
    anthropic_api_key: SecretStr | None = None

    # Local services (dev defaults match infra/docker-compose.yml).
    database_url: str = "postgresql://ips:ips-dev-password@localhost:5432/ips"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str = "ips-documents"
    matchbox_url: str = "http://localhost:8080/matchboxv3/fhir"
    terminology_server_url: str = "https://tx.fhir.org/r4"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
