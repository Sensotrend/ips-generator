"""Application settings, read from environment variables only (never from files in the repo)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmProvider(StrEnum):
    """Where LLM requests go (PLAN.md §7.1 D-5, §7.2).

    ``anthropic`` (first-party Claude API) is for development with synthetic data only;
    ``bedrock`` / ``vertex`` (EU regional endpoints) are chosen before any real data (Phase 5)
    and are not implemented yet.
    """

    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    VERTEX = "vertex"


class ExtractorKind(StrEnum):
    """Which extractor the API/worker pipeline uses (Phase 3).

    ``claude`` calls the real extraction step (`app.pipeline.extract`). ``replay`` is dev only:
    it answers with the gold extraction of an eval dataset document whose bytes match exactly,
    so the whole app can be exercised without paid API calls.
    """

    CLAUDE = "claude"
    REPLAY = "replay"


class AuthMode(StrEnum):
    """How the API identifies the reviewer. ``dev`` = fixed identity, development only.
    ``oidc`` (Keycloak, PLAN Phase 3) is not implemented yet."""

    DEV = "dev"
    OIDC = "oidc"


_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings. Every field maps to the upper-case env var of the same name."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    app_env: str = "development"
    log_level: str = "INFO"

    # LLM provider (D-5). Model ids are configured per step in app/llm/models.py, not here.
    llm_provider: LlmProvider = LlmProvider.ANTHROPIC

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

    # ---- Phase 2: terminology coding (app/terminology, app/pipeline/terminology.py) --------
    terminology_timeout_s: float = 20.0
    terminology_max_retries: int = 2
    """Retries for connection errors, timeouts, 429 and 5xx (exponential backoff)."""
    terminology_min_interval_s: float = 0.2
    """Minimum time between two requests of one client (tx.fhir.org is a shared test server)."""
    terminology_cache_size: int = 4096
    """Entries in the in-memory LRU cache of terminology answers (no disk cache: PHI)."""
    terminology_search_count: int = 10
    """Candidates returned per search."""
    terminology_max_tool_calls_per_field: int = 4
    terminology_max_tool_calls_per_document: int = 60
    terminology_fields_per_conversation: int = 20
    """Codable fields sent to Claude in one tool-loop conversation (bounded context)."""
    terminology_max_turns: int = 8
    """Model requests per conversation; the last one has tools disabled so Claude must answer."""
    terminology_mode: Literal["off", "deterministic", "llm"] = "off"
    """Terminology coding in the API/worker pipeline: ``off``; ``deterministic`` (free lookups only,
    no Claude); ``llm`` (deterministic pass + Claude tool loop, paid)."""

    # ---- Phase 3: API + worker -------------------------------------------------------------
    extractor: ExtractorKind = ExtractorKind.CLAUDE
    replay_dataset_dir: Path = _REPO_ROOT / "evals" / "dataset"
    """Where the replay extractor looks for ``<case>/document.*`` + ``gold.json``."""
    auth_mode: AuthMode = AuthMode.DEV
    dev_reviewer_name: str = "Dev Reviewer"
    validate_with_matchbox: bool = True
    """Validate drafts and approved Bundles in Matchbox. Approval requires a passing validation
    when enabled."""
    job_timeout_s: int = 900
    """Hard limit for one pipeline job in the worker (covers hostile/slow PDF parsing)."""
    job_queue_name: str = "ips-pipeline"
    run_jobs_inline: bool = False
    """Run pipeline jobs in the API process instead of RQ (tests / single-process dev only)."""

    # ---- Wallet export ("store in a digital wallet") ---------------------------------------
    wallet_issuer_url: str = "https://ips.digicredential.eu/issue"
    """Credential issuer that turns an IPS Bundle into an OpenID4VCI credential offer. The default
    is the public demo service of Findynet (not for real patient data: set your own issuer before
    Phase 5). Empty string disables the wallet export."""
    wallet_issuer_timeout_s: float = 30.0

    @property
    def is_development(self) -> bool:
        return self.app_env.strip().lower() == "development"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
