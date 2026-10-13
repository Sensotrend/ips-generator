"""Command line of ``evals/run_evals.py`` (see that file and ``evals/RESULTS.md`` for usage)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.llm.client import create_client
from app.llm.models import PipelineStep, get_step_config
from app.llm.prompts import load_extract_prompt, load_prompt
from app.pipeline.validate import MatchboxClient
from app.schemas.intermediate import SCHEMA_VERSION
from evals.cases import DATASET_DIR, EVALS_DIR, load_cases, select_cases
from evals.judge import JUDGE_PROMPT, LlmJudge, estimate_judge_call_usd
from evals.pricing import PRICES_AS_OF, CostGuard
from evals.runner import (
    CachedExtractor,
    Extractor,
    LiveExtractor,
    check_prices,
    estimate_case_cost,
    gold_extractor,
    run_dir_name,
    run_eval,
)

__all__ = ["main", "parse_args"]

RUNS_DIR = EVALS_DIR / "runs"
RESULTS_MD = EVALS_DIR / "RESULTS.md"
DEFAULT_MAX_COST_USD = 5.0
JUDGE_CALLS_PER_CASE_BOUND = 3
"""Pre-flight bound: at most one judge call per item section per case."""
JUDGE_PAYLOAD_CHARS_GUESS = 3_000


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_evals.py",
        description="Score the extraction pipeline against the gold eval dataset.",
    )
    parser.add_argument(
        "--predictions",
        choices=("gold", "cached", "live"),
        required=True,
        help="gold: gold.json as prediction (harness self-test, no API); cached: re-score a "
        "saved run (--run); live: call the extraction model (PAID, asks for confirmation).",
    )
    parser.add_argument("--run", type=Path, help="run directory to re-score (cached mode)")
    parser.add_argument(
        "--cases", nargs="+", metavar="PATTERN", help="case id prefixes or globs (e.g. fi0* en01)"
    )
    parser.add_argument("--concurrency", type=int, default=2, help="parallel API calls (live)")
    parser.add_argument("--validate", action="store_true", help="validate Bundles in Matchbox")
    parser.add_argument("--matchbox-url", help="default: MATCHBOX_URL / app settings")
    parser.add_argument(
        "--judge", action="store_true", help="LLM judge for unmatched leftovers (PAID; off)"
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=DEFAULT_MAX_COST_USD,
        help=f"hard stop for paid calls in this run (default {DEFAULT_MAX_COST_USD})",
    )
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    parser.add_argument(
        "--append-results", action="store_true", help="append the summary to evals/RESULTS.md"
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR, help="where run dirs go")
    parser.add_argument("--quiet", action="store_true", help="no per-case progress lines")
    args = parser.parse_args(argv)
    if args.predictions == "cached" and args.run is None:
        parser.error("--predictions cached needs --run <dir>")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    return args


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", *args],  # noqa: S607
            cwd=EVALS_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _env_overrides() -> dict[str, str]:
    return {
        k: v
        for k, v in sorted(os.environ.items())
        if k.upper().startswith(("IPS_MODEL_", "IPS_EFFORT_"))
    }


def _confirm(question: str, *, assume_yes: bool, ask: Callable[[str], str] = input) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Not a terminal: pass --yes to confirm a paid run.", file=sys.stderr)
        return False
    return ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _matchbox(url: str | None) -> MatchboxClient | None:
    base = (url or get_settings().matchbox_url).rstrip("/")
    try:
        httpx.get(f"{base}/metadata", timeout=30.0).raise_for_status()
    except httpx.HTTPError as exc:
        print(
            f"Matchbox not reachable at {base} ({type(exc).__name__}); skipping validation. "
            "Start it with: docker compose -f infra/docker-compose.yml up -d matchbox",
            file=sys.stderr,
        )
        return None
    return MatchboxClient(base)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    def say(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    all_cases = load_cases(args.dataset)
    try:
        cases = select_cases(all_cases, args.cases)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    now = dt.datetime.now(dt.UTC)
    extract_step = get_step_config(PipelineStep.EXTRACT)
    judge_step = get_step_config(PipelineStep.EVAL_JUDGE)
    use_judge = args.judge and args.predictions != "gold"
    if args.judge and not use_judge:
        print("Note: --judge is not needed with gold predictions (nothing is left over).")

    metadata: dict[str, Any] = {
        "date": now.isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "predictions": args.predictions,
        "cases": [c.case_id for c in cases],
        "dataset_size": len(all_cases),
        "schema_version": SCHEMA_VERSION,
        "validate": args.validate,
        "judge": use_judge,
        "judge_model": judge_step.model if use_judge else None,
        "judge_effort": judge_step.effort.value if use_judge and judge_step.effort else None,
        "judge_prompt": load_prompt(*JUDGE_PROMPT).id if use_judge else None,
        "env_overrides": _env_overrides(),
        "max_cost_usd": args.max_cost_usd,
        "prices_as_of": PRICES_AS_OF,
    }

    guard = CostGuard(args.max_cost_usd)
    estimate_total = 0.0
    extractor: Extractor
    save_predictions = False
    judge_seed_dir: Path | None = None
    estimates: dict[str, float] = {}
    if args.predictions == "gold":
        extractor = gold_extractor
        metadata |= {"extract_model": "gold", "extract_effort": None, "prompt_version": "gold"}
        run_dir = args.runs_dir / run_dir_name(now, "gold", "gold")
    elif args.predictions == "cached":
        source: Path = args.run.resolve()
        extractor = CachedExtractor(source)
        source_meta: dict[str, Any] = {}
        if (source / "run.json").is_file():
            source_meta = json.loads((source / "run.json").read_text("utf-8"))
        metadata |= {
            "source_run": source.name,
            "extract_model": source_meta.get("extract_model"),
            "extract_effort": source_meta.get("extract_effort"),
            "prompt_version": source_meta.get("prompt_version"),
            "extraction_schema_version": source_meta.get("schema_version"),
            "env_overrides": source_meta.get("env_overrides", {}),
        }
        run_dir = args.runs_dir / run_dir_name(now, "rescore", source.name)
        judge_seed_dir = source
    else:
        prompt = load_extract_prompt()
        check_prices(extract_step.model)
        estimates = {c.case_id: estimate_case_cost(c, extract_step, prompt) for c in cases}
        estimate_total += sum(estimates.values())
        metadata |= {
            "extract_model": extract_step.model,
            "extract_effort": extract_step.effort.value if extract_step.effort else None,
            "prompt_version": prompt.id,
            "estimated_extraction_cost_usd": round(sum(estimates.values()), 4),
            "concurrency": args.concurrency,
        }
        say(
            f"Live extraction: {len(cases)} cases with {extract_step.model} @ "
            f"{metadata['extract_effort']}, prompt {prompt.id}. Estimated cost "
            f"${sum(estimates.values()):.2f} (max per case ${max(estimates.values()):.3f}; "
            "character-based estimate, see evals/pricing.py)."
        )
        run_dir = args.runs_dir / run_dir_name(now, extract_step.model, prompt.id)
        save_predictions = True

    if use_judge:
        check_prices(judge_step.model)
        per_call = estimate_judge_call_usd(
            judge_step, load_prompt(*JUDGE_PROMPT), JUDGE_PAYLOAD_CHARS_GUESS
        )
        bound = per_call * JUDGE_CALLS_PER_CASE_BOUND * len(cases)
        estimate_total += bound
        say(
            f"LLM judge: {judge_step.model} @ {metadata['judge_effort']}, at most "
            f"{JUDGE_CALLS_PER_CASE_BOUND} calls per case, upper bound ${bound:.2f}."
        )

    paid = args.predictions == "live" or use_judge
    client = None
    if paid:
        say(
            f"Estimated total ${estimate_total:.2f}; hard stop at ${args.max_cost_usd:.2f} "
            f"(--max-cost-usd). Prices as of {PRICES_AS_OF}."
        )
        if estimate_total > args.max_cost_usd:
            say(
                "WARNING: the estimate exceeds --max-cost-usd; cases beyond the limit will be "
                "skipped (status 'skipped'). Raise --max-cost-usd or narrow --cases."
            )
        if not _confirm("Make paid API calls?", assume_yes=args.yes):
            print("Aborted; no API calls made.")
            return 1
        client = create_client()

    if args.predictions == "live" and client is not None:
        extractor = LiveExtractor(
            client, extract_step, load_extract_prompt(), guard, estimates=estimates
        )
    judge = LlmJudge(client, judge_step, guard) if use_judge and client is not None else None

    validator = _matchbox(args.matchbox_url) if args.validate else None
    metadata["validate"] = validator is not None
    if validator is not None:
        metadata["matchbox_url"] = validator.base_url
    metadata["run_id"] = run_dir.name

    say(f"Running {len(cases)} cases -> {run_dir}")
    try:
        output = run_eval(
            cases,
            extractor=extractor,
            run_dir=run_dir,
            metadata=metadata,
            save_predictions=save_predictions,
            concurrency=args.concurrency if args.predictions == "live" else 1,
            validator=validator,
            judge=judge,
            judge_seed_dir=judge_seed_dir,
            now=now,
            progress=say,
        )
    finally:
        if validator is not None:
            validator.close()

    print(output.markdown)
    if paid:
        print(f"Spent ${guard.spent_usd:.4f} of ${args.max_cost_usd:.2f}.")
    print(f"Results: {output.run_dir / 'results.json'}")
    if args.append_results:
        with RESULTS_MD.open("a", encoding="utf-8") as fh:
            fh.write("\n" + output.markdown)
        print(f"Appended to {RESULTS_MD}")
    return 0
