"""The per-case eval pipeline and the run directory.

Per case: ingest -> prediction (gold / cached / live extract) -> ground -> apply_grounding ->
derive (D-10, ``app.pipeline.derive``) -> ``EnrichedIps.from_extraction`` -> assemble -> optional
Matchbox validation -> score against gold (and the case's ``expected_patient``).

Run directory (``evals/runs/<UTC timestamp>_<extract model>_<prompt>/``, gitignored; synthetic
data only)::

    run.json                       run metadata (models, effort, prompt, git commit, ...)
    results.json                   metadata + RunSummary + every CaseResult
    summary.md                     markdown summary (also printed)
    cases/<case_id>/
        extraction.json            live mode: the validated model answer (IpsExtraction JSON)
        prediction.json            live mode: model, usage, cost, latency, attempts, error
        bundle.json                assembled Bundle
        judge.json                 judge decisions (only with --judge)

``--predictions cached --run <dir>`` re-scores ``extraction.json``/``prediction.json`` of an
earlier live run with the current grounding/assembly/matching code (no API calls unless
``--judge`` meets a leftover without a cached decision) into a new run directory
``<timestamp>_rescore_<source dir>``; the source run is left untouched.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from app.llm.client import LlmClient
from app.llm.models import StepModelConfig
from app.llm.prompts import Prompt
from app.pipeline.assemble import AssemblyResult, assemble
from app.pipeline.derive import derive_patient_facts
from app.pipeline.extract import ExtractionError, TokenUsage, build_user_message, extract
from app.pipeline.ground import apply_grounding, ground
from app.pipeline.validate import MatchboxClient, MatchboxError
from app.schemas.intermediate import EnrichedIps, IpsExtraction, extraction_output_format
from evals.cases import EvalCase
from evals.judge import JudgeSession, LlmJudge
from evals.matching import DocumentIndex
from evals.metrics import (
    CaseResult,
    IssueRecord,
    RunSummary,
    UsageRecord,
    ValidationRecord,
    aggregate,
    item_counts,
    score_case,
)
from evals.pricing import (
    CostGuard,
    UnknownModelPriceError,
    cost_usd,
    estimate_output_tokens,
    estimate_tokens,
    price_for,
)
from evals.report import render_markdown

logger = logging.getLogger(__name__)

__all__ = [
    "CachedExtractor",
    "Extractor",
    "LiveExtractor",
    "Prediction",
    "PredictionMeta",
    "RunOutput",
    "estimate_case_cost",
    "evaluate_case",
    "gold_extractor",
    "run_dir_name",
    "run_eval",
]

PredictionSource = Literal["gold", "cached", "live"]
_ESTIMATE_BOUNDARY = "0123456789abcdef"


class PredictionMeta(BaseModel):
    """``prediction.json``: everything about a prediction except the extraction itself."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    source: PredictionSource
    ok: bool
    skipped: bool = False
    error: str | None = None
    """Exception class name (``ExtractionRefusedError``, ``RateLimitError``, ...)."""
    error_detail: str | None = None
    """Exception message; extract.py guarantees it holds no document text."""
    model_requested: str | None = None
    model_used: str | None = None
    fallback_used: bool = False
    attempts: int = 0
    prompt_version: str | None = None
    schema_version: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    cost_is_estimate: bool = False
    """True when the call failed and its cost was booked at the estimate (usage unknown)."""
    estimated_cost_usd: float | None = None
    latency_s: float | None = None
    request_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Prediction:
    meta: PredictionMeta
    extraction: IpsExtraction | None


type Extractor = Callable[[EvalCase], Prediction]


# --------------------------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------------------------


def gold_extractor(case: EvalCase) -> Prediction:
    """Self-test: the gold extraction is the prediction (must score 100%)."""
    gold = case.load_gold()
    return Prediction(
        meta=PredictionMeta(case_id=case.case_id, source="gold", ok=True, model_used="gold"),
        extraction=gold,
    )


class CachedExtractor:
    """Reads ``cases/<case_id>/{prediction,extraction}.json`` of an earlier run."""

    def __init__(self, run_dir: Path) -> None:
        if not (run_dir / "cases").is_dir():
            raise FileNotFoundError(f"{run_dir} has no cases/ directory")
        self.run_dir = run_dir

    def __call__(self, case: EvalCase) -> Prediction:
        case_dir = self.run_dir / "cases" / case.case_id
        meta_file, extraction_file = case_dir / "prediction.json", case_dir / "extraction.json"
        if not meta_file.is_file():
            return Prediction(
                meta=PredictionMeta(
                    case_id=case.case_id,
                    source="cached",
                    ok=False,
                    skipped=True,
                    error="NotInRun",
                ),
                extraction=None,
            )
        meta = PredictionMeta.model_validate_json(meta_file.read_bytes())
        extraction = None
        if meta.ok:
            extraction = IpsExtraction.model_validate_json(extraction_file.read_bytes())
        return Prediction(meta=meta.model_copy(update={"source": "cached"}), extraction=extraction)


def estimate_case_cost(case: EvalCase, step: StepModelConfig, prompt: Prompt) -> float:
    """Estimated USD for one extraction of ``case`` (see `evals.pricing`)."""
    schema_chars = len(json.dumps(extraction_output_format()))
    user_chars = len(build_user_message(case.document, _ESTIMATE_BOUNDARY))
    usage = TokenUsage(
        input_tokens=estimate_tokens(len(prompt.text) + schema_chars + user_chars),
        output_tokens=estimate_output_tokens(len(case.gold_path.read_text("utf-8")), step.effort),
    )
    return cost_usd(step.model, usage)


class LiveExtractor:
    """Calls the real extraction step (paid). Each call reserves its estimate on the guard."""

    def __init__(
        self,
        client: LlmClient,
        step: StepModelConfig,
        prompt: Prompt,
        guard: CostGuard,
        estimates: dict[str, float],
        extract_fn: Callable[..., Any] = extract,
    ) -> None:
        self.client = client
        self.step = step
        self.prompt = prompt
        self.guard = guard
        self.estimates = estimates
        self.extract_fn = extract_fn

    def __call__(self, case: EvalCase) -> Prediction:
        estimate = self.estimates[case.case_id]
        base = PredictionMeta(
            case_id=case.case_id,
            source="live",
            ok=False,
            model_requested=self.step.model,
            prompt_version=self.prompt.id,
            estimated_cost_usd=estimate,
        )
        if not self.guard.try_reserve(estimate):
            return Prediction(
                meta=base.model_copy(update={"skipped": True, "error": "CostLimitReached"}),
                extraction=None,
            )
        started = time.monotonic()
        try:
            result = self.extract_fn(case.document, client=self.client)
        except (ExtractionError, anthropic.APIError) as exc:
            # Usage of a failed call is unknown (a refusal or a repair turn still bills
            # tokens): book the estimate.
            self.guard.settle(estimate, estimate)
            meta = base.model_copy(
                update={
                    "error": type(exc).__name__,
                    "error_detail": str(exc)[:500],
                    "latency_s": time.monotonic() - started,
                    "cost_usd": estimate,
                    "cost_is_estimate": True,
                }
            )
            return Prediction(meta=meta, extraction=None)
        except BaseException:
            self.guard.settle(estimate, estimate)
            raise
        elapsed = time.monotonic() - started
        # After a server-side fallback the hops may be billed at different prices: book the
        # more expensive of the two models (an unpriced fallback model books the estimate).
        try:
            actual = max(
                cost_usd(result.model_requested, result.usage),
                cost_usd(result.model_used, result.usage),
            )
        except UnknownModelPriceError:
            actual = max(estimate, cost_usd(result.model_requested, result.usage))
        self.guard.settle(estimate, actual)
        meta = base.model_copy(
            update={
                "ok": True,
                "model_used": result.model_used,
                "fallback_used": result.fallback_used,
                "attempts": result.attempts,
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "usage": result.usage,
                "cost_usd": actual,
                "latency_s": elapsed,
                "request_ids": list(result.request_ids),
            }
        )
        return Prediction(meta=meta, extraction=result.extraction)


# --------------------------------------------------------------------------------------------
# Per-case evaluation
# --------------------------------------------------------------------------------------------


def _validation_record(client: MatchboxClient, assembly: AssemblyResult) -> ValidationRecord:
    result = client.validate(assembly.bundle)
    unmatched = result.unmatched_bundle_entries
    issues = [
        IssueRecord(
            severity=i.severity, message_id=i.message_id, path=i.path, message=i.message[:500]
        )
        for i in result.issues
        if i.severity != "information" or "does not match any known slice" in i.message
    ]
    return ValidationRecord(
        errors=len(result.errors),
        warnings=len(result.warnings),
        unmatched_entries=unmatched,
        passed=not result.errors and not unmatched,
        issues=issues,
    )


def evaluate_case(
    case: EvalCase,
    prediction: Prediction,
    *,
    now: dt.datetime,
    validator: MatchboxClient | None = None,
    judge: JudgeSession | None = None,
    case_dir: Path | None = None,
) -> CaseResult:
    meta = prediction.meta
    usage = UsageRecord(
        model_requested=meta.model_requested,
        model_used=meta.model_used,
        fallback_used=meta.fallback_used,
        attempts=meta.attempts,
        input_tokens=meta.usage.input_tokens,
        output_tokens=meta.usage.output_tokens,
        cache_creation_input_tokens=meta.usage.cache_creation_input_tokens,
        cache_read_input_tokens=meta.usage.cache_read_input_tokens,
        cost_usd=meta.cost_usd,
        latency_s=meta.latency_s,
    )
    base = CaseResult(
        case_id=case.case_id,
        language=case.language,
        format=case.format,
        doc_type=case.doc_type,
        status="ok",
        usage=usage,
    )
    if meta.skipped:
        return base.model_copy(update={"status": "skipped", "error": meta.error})

    gold = case.load_gold()
    doc = case.document
    index = DocumentIndex(doc)
    expected = case.expected_patient
    if not meta.ok or prediction.extraction is None:
        return base.model_copy(
            update={
                "status": "extraction_failed",
                "error": meta.error or "NoExtraction",
                "score": score_case(None, gold, index, expected_patient=expected),
            }
        )

    raw = prediction.extraction
    report = ground(raw, doc)
    grounded = apply_grounding(raw, report)
    derivation = derive_patient_facts(grounded.extraction.patient)
    all_flags = (*grounded.flags, *derivation.flags)
    score = score_case(
        grounded.extraction,
        gold,
        index,
        judge=judge,
        derived=derivation.derived,
        expected_patient=expected,
    )
    flags: dict[str, int] = {}
    for flag in all_flags:
        flags[flag.reason.value] = flags.get(flag.reason.value, 0) + 1

    updates: dict[str, Any] = {
        "score": score,
        "raw_counts": item_counts(raw, gold, index),
        "grounding": {status.value: n for status, n in report.counts.items()},
        "dropped": len(grounded.dropped),
        "review_flags": flags,
    }
    assembly: AssemblyResult | None = None
    try:
        enriched = EnrichedIps.from_extraction(
            grounded.extraction, patient_derived=derivation.derived
        )
        assembly = assemble(enriched, now=now, flags=all_flags)
        updates["assembly_ok"] = True
        updates["assembly_warnings"] = len(assembly.warnings)
    except Exception as exc:  # report, don't abort the run
        updates["assembly_ok"] = False
        updates["assembly_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    if assembly is not None and case_dir is not None:
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "bundle.json").write_text(assembly.bundle.to_fhir_json(), "utf-8")
    if assembly is not None and validator is not None:
        try:
            updates["validation"] = _validation_record(validator, assembly)
        except MatchboxError as exc:
            logger.warning("validation of %s failed: %s", case.case_id, exc)
    if judge is not None:
        usage = usage.model_copy(
            update={"judge_cost_usd": judge.cost_usd, "judge_calls": judge.calls}
        )
        updates["usage"] = usage
    return base.model_copy(update=updates)


# --------------------------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------------------------


def run_dir_name(now: dt.datetime, *parts: str) -> str:
    """``<UTC timestamp>_<part>_...``, e.g. ``20261008T120000Z_claude-opus-5-5_extract_v2``."""
    stamp = now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = ["".join(c if c.isalnum() or c in "-._" else "-" for c in p) for p in parts if p]
    return "_".join([stamp, *safe])


def save_prediction(run_dir: Path, prediction: Prediction) -> None:
    case_dir = run_dir / "cases" / prediction.meta.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "prediction.json").write_text(prediction.meta.model_dump_json(indent=1), "utf-8")
    if prediction.extraction is not None:
        (case_dir / "extraction.json").write_text(
            prediction.extraction.model_dump_json(indent=1), "utf-8"
        )


@dataclass(frozen=True)
class RunOutput:
    summary: RunSummary
    cases: list[CaseResult]
    markdown: str
    run_dir: Path


def run_eval(
    cases: Sequence[EvalCase],
    *,
    extractor: Extractor,
    run_dir: Path,
    metadata: dict[str, Any],
    save_predictions: bool = False,
    concurrency: int = 1,
    validator: MatchboxClient | None = None,
    judge: LlmJudge | None = None,
    judge_seed_dir: Path | None = None,
    now: dt.datetime | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
) -> RunOutput:
    """Run the pipeline over ``cases`` and write ``results.json`` / ``summary.md``."""
    now = now or dt.datetime.now(dt.UTC)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=1, default=str), "utf-8")

    def predict(case: EvalCase) -> Prediction:
        prediction = extractor(case)
        if save_predictions:
            save_prediction(run_dir, prediction)
        status = (
            "skipped" if prediction.meta.skipped else ("ok" if prediction.meta.ok else "failed")
        )
        progress(f"  extract {case.case_id}: {status}")
        return prediction

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            predictions = list(pool.map(predict, cases))
    else:
        predictions = [predict(case) for case in cases]

    results: list[CaseResult] = []
    for case, prediction in zip(cases, predictions, strict=True):
        case_dir = run_dir / "cases" / case.case_id
        session = None
        if judge is not None:
            seed = (
                judge_seed_dir / "cases" / case.case_id / "judge.json" if judge_seed_dir else None
            )
            session = judge.session(case_dir / "judge.json", seed)
        result = evaluate_case(
            case, prediction, now=now, validator=validator, judge=session, case_dir=case_dir
        )
        results.append(result)
        progress(f"  score {case.case_id}: {result.status}")

    summary = aggregate(results, validation_ran=validator is not None)
    markdown = render_markdown(metadata, summary)
    payload = {
        "run": metadata,
        "summary": summary.model_dump(mode="json"),
        "cases": [r.model_dump(mode="json") for r in results],
    }
    (run_dir / "results.json").write_text(json.dumps(payload, indent=1, default=str), "utf-8")
    (run_dir / "summary.md").write_text(markdown, "utf-8")
    return RunOutput(summary=summary, cases=results, markdown=markdown, run_dir=run_dir)


def check_prices(*models: str) -> None:
    """Fail closed before a paid run if any model has no price."""
    for model in models:
        price_for(model)
