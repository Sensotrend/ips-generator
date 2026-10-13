"""Tests for the provider-agnostic client factory and the versioned prompt loader."""

from __future__ import annotations

import logging
import re

import anthropic
import pytest
from pydantic import SecretStr

from app.config import LlmProvider, Settings
from app.llm.client import LlmClientConfigError, create_client
from app.llm.prompts import EXTRACT_PROMPT_VERSION, load_extract_prompt, load_prompt


def test_provider_defaults_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert Settings().llm_provider is LlmProvider.ANTHROPIC


def test_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "vertex")
    assert Settings().llm_provider is LlmProvider.VERTEX


def test_anthropic_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_LOG", raising=False)
    client = create_client(Settings(anthropic_api_key=SecretStr("test-key")), max_retries=0)
    assert client.provider is LlmProvider.ANTHROPIC
    assert isinstance(client.sdk, anthropic.Anthropic)
    assert client.sdk.api_key == "test-key"
    assert client.sdk.max_retries == 0
    assert client.supports_server_side_fallbacks


@pytest.mark.parametrize("provider", [LlmProvider.BEDROCK, LlmProvider.VERTEX])
def test_cloud_providers_not_implemented_yet(provider: LlmProvider) -> None:
    with pytest.raises(NotImplementedError, match=provider.value):
        create_client(Settings(llm_provider=provider))


def test_sdk_debug_logging_refused_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_LOG", "debug")
    with pytest.raises(LlmClientConfigError):
        create_client(Settings(app_env="production", anthropic_api_key=SecretStr("k")))


def test_sdk_logger_raised_above_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_LOG", raising=False)
    sdk_logger = logging.getLogger("anthropic")
    monkeypatch.setattr(sdk_logger, "level", logging.DEBUG)
    create_client(Settings(anthropic_api_key=SecretStr("k")))
    assert sdk_logger.getEffectiveLevel() >= logging.INFO


def test_extract_prompt_loads_with_version() -> None:
    prompt = load_extract_prompt()
    assert prompt.version == EXTRACT_PROMPT_VERSION
    assert prompt.id == f"extract_{EXTRACT_PROMPT_VERSION}"
    assert prompt is load_extract_prompt()  # cached, byte-identical across requests
    assert len(prompt.sha256) == 64


def test_extract_prompt_covers_the_rules() -> None:
    text = load_extract_prompt().text
    for phrase in (
        "boundary token",
        "Never follow instructions",
        "source_quote",
        "locator",
        "Never supply a code from your own knowledge",
        "printed_code",
        "none_known_statements",
        "none_known",
        "no_information",
        "Do not translate",
        # v3: the gold-authoring rules of evals/dataset/README.md
        "reason_text",
        "never from a heading",
        "never used to derive",
        "strength_text",
        "most informative occurrence",
        '`"allergies": []`',
        # v4: frequency from a time of day, trigger-only use, sites the diagnosis name needs
        "A single time of day",
        "on a stated trigger",
        "the diagnosis name needs",
    ):
        assert phrase in text


def test_released_extract_prompt_versions_stay_loadable() -> None:
    assert "Never output codes" in load_prompt("extract", "v1").text  # history is kept as is
    assert "Silence is never" in load_prompt("extract", "v2").text
    current = load_extract_prompt().text
    assert all(load_prompt("extract", v).text != current for v in ("v1", "v2", "v3"))


def test_extract_prompt_is_static() -> None:
    text = load_extract_prompt().text
    assert not re.search(r"\{[a-z_]+\}", text)  # no template placeholders
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", text)  # no dates


@pytest.mark.parametrize(("name", "version"), [("../x", "v1"), ("extract", "1"), ("Extract", "v1")])
def test_load_prompt_rejects_bad_names(name: str, version: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        load_prompt(name, version)


def test_load_prompt_missing_version() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("extract", "v999")
