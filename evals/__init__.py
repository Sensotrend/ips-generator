"""Phase 1 evaluation harness (PLAN.md §5, §6 Phase 1, §7.1 D-3).

Entry point: ``evals/run_evals.py`` (run from ``backend/``). Modules:

* `evals.cases` - loading dataset cases (``evals/dataset/<case_id>/``);
* `evals.matching` - deterministic predicted-to-gold item matching;
* `evals.metrics` - per-case scores and dataset aggregates;
* `evals.pricing` - price table, cost estimates and the cost guard;
* `evals.judge` - optional LLM judge for unmatched leftovers;
* `evals.runner` - the per-case pipeline and the run directory;
* `evals.report` - markdown summary.
"""
