# Eval results

Recorded runs of `evals/run_evals.py` against the Phase 1 dataset (`evals/dataset/`, 26 synthetic
cases). Newest runs are appended at the end (`--append-results`). Per CLAUDE.md, run the evals for
every extraction or prompt change and record the result here.

## How to run

From `backend/` (the harness imports `app` and uses the backend's uv environment):

```sh
# Harness self-test: gold.json as the prediction. Free; must score 100% on extraction metrics.
uv run python ../evals/run_evals.py --predictions gold

# ... plus Matchbox validation of every assembled Bundle (Phase 1 "done when" metric).
docker compose -f ../infra/docker-compose.yml up -d matchbox   # wait until healthy (~70 s+)
uv run python ../evals/run_evals.py --predictions gold --validate

# PAID: real extraction with the configured EXTRACT model. Prints an estimate and asks first
# (or pass --yes); stops starting new calls once --max-cost-usd (default 5) would be exceeded.
ANTHROPIC_API_KEY=... uv run python ../evals/run_evals.py --predictions live --validate \
    --max-cost-usd 3 --append-results

# Another model / effort for one run (recorded in the run metadata):
IPS_MODEL_EXTRACT=claude-sonnet-5-5 IPS_EFFORT_EXTRACT=high \
    uv run python ../evals/run_evals.py --predictions live --validate

# Re-score a saved run with the current grounding / assembly / matching code (no API calls):
uv run python ../evals/run_evals.py --predictions cached --run ../evals/runs/<run dir> --validate
```

Options: `--cases fi0* en01` (id prefixes or globs), `--concurrency N` (parallel API calls in
live mode, default 2), `--judge` (LLM judge for unmatched leftovers, paid, off by default; model
from the `EVAL_JUDGE` step, `IPS_MODEL_EVAL_JUDGE` / `IPS_EFFORT_EVAL_JUDGE`), `--matchbox-url`,
`--runs-dir`, `--quiet`, `--yes`, `--append-results`.

Each run writes `evals/runs/<UTC timestamp>_<model>_<prompt>/` (gitignored; synthetic data only):
`run.json` (metadata), `results.json` (summary + every case), `summary.md`, and per case
`cases/<case_id>/{extraction.json, prediction.json, bundle.json, judge.json}` (raw model answer
and usage only in live runs). Cached re-scores go to `<timestamp>_rescore_<source run>/`.

## Cost

A live run asks before it spends. The estimate is character-based (`evals/pricing.py`: 3 chars
per token for input incl. the system prompt and the ~20 KB output schema; output = gold JSON size
plus a thinking allowance of 8K tokens at `high` effort), because `count_tokens` needs an API key
and is not documented as free in the bundled API docs. Prices: one table in `evals/pricing.py`
(Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50 per MTok, as of 2026-10-07). The cost
guard reserves each call's estimate before it starts and books the actual usage afterwards; a
failed call is booked at its estimate. Replace the estimate with measured numbers after the
first live run.

## Metrics

Matching (D-3, deterministic first; `evals/matching.py`): per section, predicted and gold items
are compared by their primary text (substance / medication / condition; NFKC + case-fold +
punctuation removed, printed ATC/ICD-10 codes and, for medications, strengths stripped,
order-insensitive token F1 with a cheap prefix rule for Finnish/Swedish inflection) and by the
character overlap of their `source_quote` spans in the document. A pair matches on text
similarity >= 0.8, or on quote overlap (>= 50% of the longer span, or >= 90% of the shorter with
some text similarity). One-to-one assignment, greedy by score. Leftovers go to the LLM judge with
`--judge`, else count as FP / FN.

- **Items**: precision, recall, F1 per section (allergies, medications, problems, D-7
  `allergy_statements`, patient names / identifiers / birth date / gender). Micro = summed counts;
  macro = mean per-case F1 over cases with at least one gold or predicted item.
- **Section state** accuracy (items_found / none_known / no_information) with a confusion matrix.
  **Critical**: none_known predicted where gold has items, or items predicted where gold says
  none known. **False assurance**: none_known where gold has no information.
- **Field accuracy** on matched items: statuses, criticality, type/category, dates (exact, and
  lenient = one is a prefix of the other), printed codes, strength, as-needed, presence of
  dosage text / body site / reactions; D-7 statement scope.
- **Grounding**: status distribution of predicted facts, dropped facts, review flags; recall
  before grounding is reported too.
- **Assembly** success and, with `--validate`, **validator pass rate**: Matchbox reports 0 errors
  **and** no unmatched Bundle entry, over all cases run (failed extractions count as fails).
  Phase 1 is done at >= 90%.
- Breakdowns per language and per format; tokens, cost, latency, fallbacks, refusals, repair
  turns, errors.

Scores are computed on the grounded extraction (what the pipeline assembles).

## Runs

_No recorded runs yet._
