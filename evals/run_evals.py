"""Phase 1 eval runner: score the extraction pipeline against ``evals/dataset`` gold.

Run from ``backend/`` (uses the backend's uv environment and imports ``app``)::

    uv run python ../evals/run_evals.py --predictions gold                 # self-test, free
    uv run python ../evals/run_evals.py --predictions gold --validate      # + Matchbox
    uv run python ../evals/run_evals.py --predictions live --validate      # PAID: asks first
    uv run python ../evals/run_evals.py --predictions cached --run ../evals/runs/<dir>

Per case: ingest -> extract (or gold / cached) -> ground -> apply_grounding ->
EnrichedIps.from_extraction -> assemble -> (Matchbox validate) -> score. See
``evals/RESULTS.md`` for options, metric definitions and recorded results.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _path in (_REPO, _REPO / "backend"):  # `evals` package and the backend `app` package
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

if __name__ == "__main__":
    from evals.cli import main

    raise SystemExit(main())
