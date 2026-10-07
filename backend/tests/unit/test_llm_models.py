"""Tests for per-step model/effort configuration (PLAN.md §8.1)."""

import pytest
from pydantic import ValidationError

from app.llm.models import (
    Effort,
    ModelSettings,
    PipelineStep,
    StepModelConfig,
    get_model_settings,
    get_step_config,
)

EXPECTED_DEFAULTS: dict[PipelineStep, tuple[str, Effort]] = {
    PipelineStep.CLASSIFY: ("claude-sonnet-5-5", Effort.LOW),
    PipelineStep.EXTRACT: ("claude-opus-5-5", Effort.HIGH),
    PipelineStep.TERMINOLOGY: ("claude-sonnet-5-5", Effort.MEDIUM),
    PipelineStep.REPAIR: ("claude-opus-5-5", Effort.MEDIUM),
    PipelineStep.MERGE: ("claude-opus-5-5", Effort.HIGH),
    PipelineStep.EVAL_JUDGE: ("claude-sonnet-5-5", Effort.MEDIUM),
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for step in PipelineStep:
        monkeypatch.delenv(f"IPS_MODEL_{step.name}", raising=False)
        monkeypatch.delenv(f"IPS_EFFORT_{step.name}", raising=False)
    get_model_settings.cache_clear()


def test_every_step_has_expected_default() -> None:
    assert set(EXPECTED_DEFAULTS) == set(PipelineStep)
    settings = ModelSettings()
    for step, (model, effort) in EXPECTED_DEFAULTS.items():
        assert settings.for_step(step) == StepModelConfig(step=step, model=model, effort=effort)


def test_env_overrides_model_and_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPS_MODEL_EXTRACT", "claude-sonnet-5-5")
    monkeypatch.setenv("IPS_EFFORT_EXTRACT", "medium")
    config = get_step_config(PipelineStep.EXTRACT)
    assert config.model == "claude-sonnet-5-5"
    assert config.effort is Effort.MEDIUM
    # Other steps are unaffected.
    assert get_step_config(PipelineStep.REPAIR).model == "claude-opus-5-5"


def test_effort_none_omits_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPS_MODEL_CLASSIFY", "claude-haiku-4-5")
    monkeypatch.setenv("IPS_EFFORT_CLASSIFY", "none")
    config = ModelSettings().for_step(PipelineStep.CLASSIFY)
    assert config.model == "claude-haiku-4-5"
    assert config.effort is None


def test_invalid_effort_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPS_EFFORT_REPAIR", "extreme")
    with pytest.raises(ValidationError):
        ModelSettings()


def test_empty_model_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPS_MODEL_MERGE", "  ")
    with pytest.raises(ValidationError):
        ModelSettings()


def test_step_config_is_frozen() -> None:
    config = ModelSettings().for_step(PipelineStep.MERGE)
    with pytest.raises(ValidationError):
        config.model = "other"  # type: ignore[misc]
