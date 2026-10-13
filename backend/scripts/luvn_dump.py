"""Build per-patient LUVN JSON dumps from the LUVN clinical table files (no LLM, stdlib only).

Run from ``backend/``::

    uv run python -m scripts.luvn_dump import <clinical/tables dir> <sqlite file>
    uv run python -m scripts.luvn_dump dump <sqlite file> <out dir> [filters] [--limit N]

Filters (all that are given must hold): ``--id <id>`` (repeatable), ``--with-labs``,
``--with-procedures``, ``--has-long-term-dx``, ``--active-meds``, ``--min-score N``,
``--random-seed S`` (shuffle before ``--limit``). ``--limit N`` stops after N dumps that pass
every filter (the first N, not the best); ``--top N`` ranks all matching patients by score and
dumps the N best. Besides ``<asiakas_id>.json`` per patient, ``manifest.json`` lists the files best
first (see ``app.sources.luvn.manifest``). Prints counts and file names only, never row contents.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from app.sources.luvn.dump import PatientFilter, dump_patient, import_tables, select_patient_ids
from app.sources.luvn.manifest import build_manifest, summarise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="load the table files into SQLite")
    imp.add_argument("tables_dir", type=Path)
    imp.add_argument("db", type=Path)
    out = sub.add_parser("dump", help="write one dump file per patient and a manifest")
    out.add_argument("db", type=Path)
    out.add_argument("out_dir", type=Path)
    out.add_argument("--id", action="append", default=[], help="asiakas_id (repeatable)")
    out.add_argument("--with-labs", action="store_true")
    out.add_argument("--with-procedures", action="store_true")
    out.add_argument("--has-long-term-dx", action="store_true")
    out.add_argument("--active-meds", action="store_true")
    out.add_argument("--min-score", type=int, default=0)
    out.add_argument("--random-seed", type=int)
    out.add_argument("--limit", "--first", dest="limit", type=int, help="at most N dumps")
    out.add_argument("--top", type=int, help="the N highest-scoring patients (ranks all first)")
    out.add_argument("--exported-at", type=dt.date.fromisoformat, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "import":
        counts = import_tables(args.tables_dir, args.db)
        for table, n in counts.items():
            print(f"{table}: {n} rows")
        return 0

    exported_at: dt.date = args.exported_at or dt.date.today()
    flt = PatientFilter(
        ids=tuple(args.id),
        with_labs=args.with_labs,
        with_procedures=args.with_procedures,
        has_long_term_dx=args.has_long_term_dx,
        active_meds=args.active_meds,
        random_seed=args.random_seed,
    )
    filters: dict[str, Any] = {**flt.describe()}
    if args.min_score:
        filters["min_score"] = args.min_score
    if args.limit:
        filters["limit"] = args.limit
    if args.top:
        filters["top"] = args.top
    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    with sqlite3.connect(args.db) as con:
        candidates = select_patient_ids(con, flt, exported_at=exported_at)
        wanted = candidates
        if args.top:  # rank every candidate first, then dump only the best
            scored = (
                (summarise(dump_patient(con, i, exported_at=exported_at))["score"], i)
                for i in candidates
            )
            ranked = sorted((-score, i) for score, i in scored if score >= args.min_score)
            wanted = [i for _, i in ranked[: args.top]]
        for asiakas_id in wanted:
            if args.limit and len(entries) >= args.limit:
                break
            dump = dump_patient(con, asiakas_id, exported_at=exported_at)
            summary = summarise(dump)
            if summary["score"] < args.min_score:
                continue
            name = f"{asiakas_id}.json"
            text = json.dumps(dump, ensure_ascii=False, indent=2) + "\n"
            (args.out_dir / name).write_text(text, encoding="utf-8")
            entries.append({"file": name, **summary})
    manifest = build_manifest(entries, exported_at=exported_at, filters=filters)
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(candidates)} matched the database filters; wrote {len(entries)} dump(s)")
    for entry in manifest["patients"][:5]:
        c = entry["counts"]
        labs = entry["not_mapped"]["lab_results"]
        print(
            f"  score {entry['score']:>2}  {entry['file']}  problems {c['problems']}, "
            f"active medications {c['active_medications']}, labs {labs}"
        )
    if not entries:
        print("nothing written; check the filters", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
