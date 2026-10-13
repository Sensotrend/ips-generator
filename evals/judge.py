"""Optional LLM judge for items the deterministic matcher left unmatched (PLAN.md §7.1 D-3).

Model and effort come from the ``EVAL_JUDGE`` step in ``app/llm/models.py`` (§8.1: Sonnet 5.5 @
medium; override with ``IPS_MODEL_EVAL_JUDGE`` / ``IPS_EFFORT_EVAL_JUDGE``). The prompt is the
versioned file ``backend/app/llm/prompts/eval_judge_v1.md``. One call per section that has
leftovers on both sides; structured output ``{"matches": [{"predicted": i, "gold": j}]}``.

Every call reserves its estimated cost on the run's `CostGuard` first. Decisions are cached per
case in ``<run>/cases/<case_id>/judge.json`` (keyed by a hash of model, prompt and input), so
re-scoring a run with ``--predictions cached --judge`` reuses them without API calls.

Not yet verified against the real API (no key configured when written).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import anthropic
from anthropic.types.beta import BetaMessage

from app.llm.client import LlmClient
from app.llm.models import StepModelConfig
from app.llm.prompts import Prompt, load_prompt
from app.pipeline.extract import TokenUsage
from evals.metrics import JudgeItem
from evals.pricing import (
    CostGuard,
    CostLimitExceededError,
    cost_usd,
    estimate_output_tokens,
    estimate_tokens,
)

logger = logging.getLogger(__name__)

__all__ = ["JUDGE_PROMPT", "JudgeSession", "LlmJudge", "estimate_judge_call_usd"]

JUDGE_PROMPT: Final = ("eval_judge", "v1")
JUDGE_MAX_TOKENS: Final = 16_000
_ANSWER_CHARS: Final = 600

_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"predicted": {"type": "integer"}, "gold": {"type": "integer"}},
                "required": ["predicted", "gold"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


def _payload(section: str, pred: Sequence[JudgeItem], gold: Sequence[JudgeItem]) -> str:
    def items(values: Sequence[JudgeItem]) -> list[dict[str, Any]]:
        return [
            {"id": v.index, "text": v.text, "quote": v.quote, "details": v.details} for v in values
        ]

    return json.dumps(
        {"section": section, "predicted": items(pred), "gold": items(gold)},
        ensure_ascii=False,
        indent=1,
    )


def estimate_judge_call_usd(step: StepModelConfig, prompt: Prompt, payload_chars: int) -> float:
    usage = TokenUsage(
        input_tokens=estimate_tokens(len(prompt.text) + payload_chars + len(json.dumps(_SCHEMA))),
        output_tokens=estimate_output_tokens(_ANSWER_CHARS, step.effort),
    )
    return cost_usd(step.model, usage)


class LlmJudge:
    """Shared judge configuration (client, model, cost guard) for a run."""

    def __init__(self, client: LlmClient, step: StepModelConfig, guard: CostGuard) -> None:
        self.client = client
        self.step = step
        self.guard = guard
        self.prompt = load_prompt(*JUDGE_PROMPT)

    def session(self, cache_file: Path | None, seed_file: Path | None = None) -> JudgeSession:
        return JudgeSession(self, cache_file, seed_file)

    def call(self, payload: str) -> tuple[list[tuple[int, int]], float]:
        """One API call; returns pairs and actual cost. Raises `CostLimitExceededError`."""
        estimate = estimate_judge_call_usd(self.step, self.prompt, len(payload))
        self.guard.reserve_or_raise(estimate)
        actual = estimate  # booked at the estimate unless usage comes back
        try:
            output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": _SCHEMA}}
            if self.step.effort is not None:
                output_config["effort"] = self.step.effort.value
            params: dict[str, Any] = {
                "model": self.step.model,
                "max_tokens": JUDGE_MAX_TOKENS,
                "system": [
                    {
                        "type": "text",
                        "text": self.prompt.text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": payload}],
                "output_config": output_config,
            }
            message: BetaMessage = self.client.sdk.beta.messages.create(**params)
            usage = message.usage
            actual = cost_usd(
                message.model,
                TokenUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                    cache_read_input_tokens=usage.cache_read_input_tokens or 0,
                ),
            )
            if message.stop_reason != "end_turn":
                logger.warning(
                    "judge stopped with %s; leftovers stay unmatched", message.stop_reason
                )
                return [], actual
            text = "".join(block.text for block in message.content if block.type == "text")
            data = json.loads(text)
            pairs = [(int(m["predicted"]), int(m["gold"])) for m in data.get("matches", [])]
            return pairs, actual
        finally:
            self.guard.settle(estimate, actual)


class JudgeSession:
    """The judge for one case: per-case cache file and cost accounting."""

    def __init__(
        self, judge: LlmJudge, cache_file: Path | None, seed_file: Path | None = None
    ) -> None:
        self.judge = judge
        self.cache_file = cache_file
        self.cost_usd = 0.0
        self.calls = 0
        self.skipped = 0
        self._lock = threading.Lock()
        self._cache: dict[str, list[list[int]]] = {}
        for source in (seed_file, cache_file):  # e.g. the cached run's decisions, then ours
            if source is not None and source.is_file():
                self._cache.update(json.loads(source.read_text("utf-8")))

    def _key(self, payload: str) -> str:
        material = f"{self.judge.step.model}\n{self.judge.prompt.id}\n{payload}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def __call__(
        self, section: str, pred: Sequence[JudgeItem], gold: Sequence[JudgeItem]
    ) -> Sequence[tuple[int, int]]:
        payload = _payload(section, pred, gold)
        key = self._key(payload)
        if key in self._cache:
            return [(p, g) for p, g in self._cache[key]]
        try:
            pairs, cost = self.judge.call(payload)
        except CostLimitExceededError:
            self.skipped += 1
            logger.warning("judge skipped: cost limit reached")
            return []
        except (anthropic.APIError, ValueError, KeyError, TypeError) as exc:
            self.skipped += 1
            logger.warning("judge call failed (%s); leftovers stay unmatched", type(exc).__name__)
            return []
        with self._lock:
            self.calls += 1
            self.cost_usd += cost
            self._cache[key] = [[p, g] for p, g in pairs]
            if self.cache_file is not None:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps(self._cache, indent=1), "utf-8")
        return pairs
