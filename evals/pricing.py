"""Prices, cost estimates and the cost guard for paid eval runs.

Prices are Anthropic API list prices in USD per million tokens. Sources: PLAN.md §8.1 (as of
2026-10-07) and the claude-api skill model table (``shared/models.md``, read 2026-10-08):

* Opus 5.5 $4 / $20, cache reads $0.20 (0.05x);
* Sonnet 5.5 $2 / $10, cache reads $0.20 per the model table (the 0.05x rule of thumb would give
  $0.10; the higher figure is used so the guard errs on the expensive side);
* Haiku 5.5 $0.10 / $0.50 for prompts up to 100K tokens, $0.50 / $2.50 above; cache-read price
  not documented, assumed 0.1x;
* Fable 5.1 $10 / $50, cache reads $0.25 (only for a one-off ceiling run, PLAN §8.1).

Cache writes (5-minute TTL) are 1.25x the input price. Batch discounts are not modelled (evals
call the synchronous API). Update this table, with its date, when prices change.

Estimates (no API call): ``count_tokens`` would need an API key and the bundled docs do not
state it is free, so input tokens are estimated from characters at `CHARS_PER_TOKEN` (chosen
low, i.e. pessimistic, for Finnish/Swedish text), including the JSON schema of the structured
output. Output tokens = the gold JSON size (a proxy for the answer) at the same rate plus a
thinking allowance per effort level (`THINKING_ALLOWANCE`, a guess until measured).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Final

from app.llm.models import Effort
from app.pipeline.extract import TokenUsage

__all__ = [
    "CHARS_PER_TOKEN",
    "PRICES",
    "PRICES_AS_OF",
    "THINKING_ALLOWANCE",
    "CostGuard",
    "CostLimitExceededError",
    "ModelPrice",
    "UnknownModelPriceError",
    "cost_usd",
    "estimate_output_tokens",
    "estimate_tokens",
    "price_for",
]

PRICES_AS_OF: Final = "2026-10-07"


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float
    long_prompt_threshold: int | None = None
    """Prompts above this many input tokens are billed at the ``long_*`` prices."""
    long_input: float | None = None
    long_output: float | None = None


PRICES: Final[dict[str, ModelPrice]] = {
    "claude-opus-5-5": ModelPrice(input=4.0, output=20.0, cache_read=0.20, cache_write=5.0),
    "claude-sonnet-5-5": ModelPrice(input=2.0, output=10.0, cache_read=0.20, cache_write=2.5),
    "claude-haiku-5-5": ModelPrice(
        input=0.10,
        output=0.50,
        cache_read=0.01,
        cache_write=0.125,
        long_prompt_threshold=100_000,
        long_input=0.50,
        long_output=2.50,
    ),
    "claude-fable-5-1": ModelPrice(input=10.0, output=50.0, cache_read=0.25, cache_write=12.5),
}

CHARS_PER_TOKEN: Final = 3.0
THINKING_ALLOWANCE: Final[dict[Effort | None, int]] = {
    Effort.HIGH: 8_000,
    Effort.MEDIUM: 3_000,
    Effort.LOW: 1_000,
    None: 3_000,
}


class UnknownModelPriceError(KeyError):
    """No price for a model: paid runs fail closed rather than run unguarded."""


class CostLimitExceededError(RuntimeError):
    pass


def price_for(model: str) -> ModelPrice:
    """Price of ``model``; accepts provider prefixes and dated suffixes (``...-5-5-2026...``)."""
    name = model.removeprefix("anthropic.")
    for known, price in PRICES.items():
        if name == known or name.startswith(f"{known}-") or name.startswith(f"{known}@"):
            return price
    raise UnknownModelPriceError(f"no price for model {model!r}; add it to evals/pricing.py")


def cost_usd(model: str, usage: TokenUsage) -> float:
    price = price_for(model)
    input_price, output_price = price.input, price.output
    prompt = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
    if price.long_prompt_threshold is not None and prompt > price.long_prompt_threshold:
        input_price = price.long_input or input_price
        output_price = price.long_output or output_price
    return (
        usage.input_tokens * input_price
        + usage.output_tokens * output_price
        + usage.cache_read_input_tokens * price.cache_read
        + usage.cache_creation_input_tokens * price.cache_write
    ) / 1_000_000


def estimate_tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


def estimate_output_tokens(answer_chars: int, effort: Effort | None) -> int:
    return estimate_tokens(answer_chars) + THINKING_ALLOWANCE[effort]


class CostGuard:
    """Hard spending limit shared by all paid calls of a run (thread-safe).

    A call may start only if ``spent + reserved + its estimate <= limit``; when it finishes its
    reservation is replaced by its actual cost (usage x `PRICES`). In-flight calls can still
    overshoot their estimate, so the limit can be exceeded by at most the overshoot of the calls
    running at that moment (keep ``--concurrency`` small).
    """

    def __init__(self, limit_usd: float) -> None:
        if limit_usd < 0:
            raise ValueError("limit must be >= 0")
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self.reserved_usd = 0.0
        self.refused = 0
        self._lock = threading.Lock()

    def try_reserve(self, estimate_usd: float) -> bool:
        with self._lock:
            if self.spent_usd + self.reserved_usd + estimate_usd > self.limit_usd:
                self.refused += 1
                return False
            self.reserved_usd += estimate_usd
            return True

    def settle(self, estimate_usd: float, actual_usd: float) -> None:
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - estimate_usd)
            self.spent_usd += actual_usd

    def reserve_or_raise(self, estimate_usd: float) -> None:
        if not self.try_reserve(estimate_usd):
            raise CostLimitExceededError(
                f"cost limit ${self.limit_usd:.2f} reached (spent ${self.spent_usd:.4f})"
            )
