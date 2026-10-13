"""Manual smoke test: one real extraction of the synthetic Finnish discharge summary.

Makes one paid API call (synthetic data only). Prints token usage and the grounding summary,
never document text or model output. Run from ``backend/``::

    ANTHROPIC_API_KEY=... uv run python -m scripts.smoke_extract
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from app.pipeline.extract import ExtractionError, extract
from app.pipeline.ground import apply_grounding, ground
from app.pipeline.ingest import ingest

FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests/fixtures/intermediate/discharge_summary_fi.txt"
)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; nothing to do.", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    doc = ingest(FIXTURE.read_bytes(), "text/plain")
    started = time.monotonic()
    try:
        result = extract(doc)
    except ExtractionError as exc:  # messages contain no document text
        print(f"extraction failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started

    report = ground(result.extraction, doc)
    grounded = apply_grounding(result.extraction, report)

    print(f"model requested/used: {result.model_requested} / {result.model_used}")
    print(f"fallback used: {result.fallback_used}  attempts: {result.attempts}")
    print(f"prompt: {result.prompt_version}  schema: {result.schema_version}")
    print(f"request ids: {', '.join(result.request_ids)}")
    print(f"elapsed: {elapsed:.1f}s")
    print(f"usage: {result.usage.model_dump()}")
    print("grounding: " + ", ".join(f"{k.value}={v}" for k, v in report.counts.items()))
    for flag in grounded.flags:
        print(f"  review flag: {flag.path} ({flag.reason.value})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
