"""Per-pipeline-step model and effort configuration (PLAN.md §8.1, "Start" column).

Every step can be overridden with environment variables:
``IPS_MODEL_<STEP>`` (model id) and ``IPS_EFFORT_<STEP>`` (``low``/``medium``/``high``, or
``none`` to omit the effort parameter, e.g. for models that do not support it).
Example: ``IPS_MODEL_EXTRACT=claude-sonnet-5-5 IPS_EFFORT_EXTRACT=high``.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineStep(StrEnum):
    """Pipeline steps that call an LLM."""

    CLASSIFY = "classify"
    EXTRACT = "extract"
    TERMINOLOGY = "terminology"
    REPAIR = "repair"
    MERGE = "merge"
    EVAL_JUDGE = "eval_judge"


class Effort(StrEnum):
    """Value for the Messages API ``output_config.effort`` parameter."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StepModelConfig(BaseModel):
    """Resolved model + effort for one pipeline step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: PipelineStep
    model: str
    effort: Effort | None


def _parse_effort(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in {"", "none"}:
        return None
    return value


class ModelSettings(BaseSettings):
    """Env-overridable defaults. Field names map to ``IPS_MODEL_<STEP>`` / ``IPS_EFFORT_<STEP>``."""

    model_config = SettingsConfigDict(
        env_prefix="IPS_", case_sensitive=False, extra="ignore", frozen=True
    )

    model_classify: str = "claude-sonnet-5-5"
    effort_classify: Effort | None = Effort.LOW
    model_extract: str = "claude-opus-5-5"
    effort_extract: Effort | None = Effort.HIGH
    model_terminology: str = "claude-sonnet-5-5"
    effort_terminology: Effort | None = Effort.MEDIUM
    model_repair: str = "claude-opus-5-5"
    effort_repair: Effort | None = Effort.MEDIUM
    model_merge: str = "claude-opus-5-5"
    effort_merge: Effort | None = Effort.HIGH
    model_eval_judge: str = "claude-sonnet-5-5"
    effort_eval_judge: Effort | None = Effort.MEDIUM

    @field_validator(
        "effort_classify",
        "effort_extract",
        "effort_terminology",
        "effort_repair",
        "effort_merge",
        "effort_eval_judge",
        mode="before",
    )
    @classmethod
    def _none_effort(cls, value: Any) -> Any:
        return _parse_effort(value)

    @field_validator(
        "model_classify",
        "model_extract",
        "model_terminology",
        "model_repair",
        "model_merge",
        "model_eval_judge",
    )
    @classmethod
    def _non_empty_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model id must not be empty")
        return value

    def for_step(self, step: PipelineStep) -> StepModelConfig:
        """Return the resolved config for ``step``."""
        model: str = getattr(self, f"model_{step.value}")
        effort: Effort | None = getattr(self, f"effort_{step.value}")
        return StepModelConfig(step=step, model=model, effort=effort)


@lru_cache
def get_model_settings() -> ModelSettings:
    """Return the process-wide model settings (read once from the environment)."""
    return ModelSettings()


def get_step_config(step: PipelineStep) -> StepModelConfig:
    """Return the model + effort configured for ``step``."""
    return get_model_settings().for_step(step)
