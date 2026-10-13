"""Provider-agnostic Anthropic SDK client factory (PLAN.md §7.1 D-5, §7.2).

Pipeline steps never construct SDK clients themselves: they call `get_client()` (or accept an
`LlmClient` for tests) and branch on its capabilities, not on the provider name. Adding Bedrock
or Vertex later means implementing their branch in `create_client()` and widening `SdkClient`;
callers keep working.

Model ids are not configured here: they come only from `app.llm.models` (per pipeline step).

PHI note: the SDK logs full request bodies (the document) at DEBUG level. `create_client()`
raises the ``anthropic`` logger to INFO, and refuses ``ANTHROPIC_LOG=debug`` outside development
(CLAUDE.md: never log document contents).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import LlmProvider, Settings, get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "LlmClient",
    "LlmClientConfigError",
    "LlmProvider",
    "SdkClient",
    "create_client",
    "get_client",
]

type SdkClient = anthropic.Anthropic
"""The SDK client type pipeline code calls (``client.sdk.beta.messages.stream(...)``).

Extension point: widen to ``anthropic.Anthropic | anthropic.AnthropicBedrock |
anthropic.AnthropicVertex`` when those providers are implemented. Their ``beta.messages``
resources expose the same call surface but are distinct classes, so mypy will then need a
small adapter (or a cast) at the one call site in each step.
"""

DEFAULT_MAX_RETRIES = 2
"""SDK retries for connection errors, 408/409/429 and 5xx (exponential backoff)."""


class LlmClientConfigError(RuntimeError):
    """The LLM client cannot be created from the current settings."""


@dataclass(frozen=True)
class LlmClient:
    """An SDK client plus what its provider supports."""

    provider: LlmProvider
    sdk: SdkClient

    @property
    def supports_server_side_fallbacks(self) -> bool:
        """Server-side refusal ``fallbacks`` (beta) exist only on the first-party API.

        Bedrock/Vertex need the SDK's client-side ``BetaRefusalFallbackMiddleware`` instead,
        registered on the client in `create_client()` (PLAN.md §7.2).
        """
        return self.provider is LlmProvider.ANTHROPIC


def create_client(
    settings: Settings | None = None,
    *,
    max_retries: int | None = None,
    http_client: anthropic.DefaultHttpxClient | None = None,
) -> LlmClient:
    """Create a client for the configured provider (``LLM_PROVIDER``).

    ``http_client`` is for proxies and tests (a mock transport); use ``DefaultHttpxClient``.
    """
    settings = settings or get_settings()
    _guard_sdk_logging(settings)
    retries = DEFAULT_MAX_RETRIES if max_retries is None else max_retries

    match settings.llm_provider:
        case LlmProvider.ANTHROPIC:
            # Without an explicit key the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN
            # or an `ant auth login` profile itself.
            api_key = (
                settings.anthropic_api_key.get_secret_value()
                if settings.anthropic_api_key is not None
                else None
            )
            sdk = anthropic.Anthropic(api_key=api_key, max_retries=retries, http_client=http_client)
            return LlmClient(provider=LlmProvider.ANTHROPIC, sdk=sdk)
        case LlmProvider.BEDROCK:
            # Phase 5: anthropic.AnthropicBedrock(aws_region=<EU region>) plus
            # BetaRefusalFallbackMiddleware; model ids need the "anthropic." prefix.
            raise NotImplementedError("LLM provider 'bedrock' is not implemented yet (PLAN D-5).")
        case LlmProvider.VERTEX:
            # Phase 5: anthropic.AnthropicVertex(region=<EU region>, project_id=...) plus
            # BetaRefusalFallbackMiddleware.
            raise NotImplementedError("LLM provider 'vertex' is not implemented yet (PLAN D-5).")


@lru_cache
def get_client() -> LlmClient:
    """Return the process-wide client (created on first use)."""
    return create_client()


def _guard_sdk_logging(settings: Settings) -> None:
    """Keep the SDK from logging request bodies (it does at DEBUG, e.g. under a DEBUG root logger).

    ``ANTHROPIC_LOG=debug`` is honoured only in development (synthetic data only).
    """
    sdk_logger = logging.getLogger("anthropic")
    if os.environ.get("ANTHROPIC_LOG", "").strip().lower() == "debug":
        if settings.app_env != "development":
            raise LlmClientConfigError(
                "ANTHROPIC_LOG=debug logs request bodies (document contents); "
                "it is only allowed when APP_ENV=development with synthetic data."
            )
        logger.warning("ANTHROPIC_LOG=debug logs request bodies; use synthetic documents only.")
        return
    if sdk_logger.getEffectiveLevel() < logging.INFO:
        sdk_logger.setLevel(logging.INFO)
