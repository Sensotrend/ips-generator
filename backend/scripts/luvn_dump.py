"""Build per-patient LUVN JSON dumps from the LUVN clinical table files (no LLM, stdlib only).

Run from ``backend/``::

    uv run python -m scripts.luvn_dump import <clinical/tables dir> <sqlite file>
    uv run python -m scripts.luvn_dump dump <sqlite file> <out dir> [--id <id>]... [--first N]

Prints counts only, never row contents.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.sources.luvn.dump import dump_patient, import_tables, patient_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="load the table files into SQLite")
    imp.add_argument("tables_dir", type=Path)
    imp.add_argument("db", type=Path)
    out = sub.add_parser("dump", help="write one dump file per patient")
    out.add_argument("db", type=Path)
    out.add_argument("out_dir", type=Path)
    out.add_argument("--id", action="append", default=[], help="asiakas_id (repeatable)")
    out.add_argument("--first", type=int, help="the first N patients")
    args = parser.parse_args(argv)

    if args.command == "import":
        counts = import_tables(args.tables_dir, args.db)
        for table, n in counts.items():
            print(f"{table}: {n} rows")
        return 0

    ids = list(args.id)
    if args.first:
        ids += patient_ids(args.db)[: args.first]
    if not ids:
        print("give --id or --first", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.db) as con:
        for asiakas_id in ids:
            dump = dump_patient(con, asiakas_id)
            path = args.out_dir / f"{asiakas_id}.json"
            path.write_text(json.dumps(dump, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(ids)} dump(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
