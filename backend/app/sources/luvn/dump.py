"""LUVN tables -> SQLite -> one JSON dump per patient.

Dump format (``meta.format == "luvn-clinical-dump"``)::

    {"meta": {"format": "luvn-clinical-dump", "version": 1, "exported_at": "2026-10-13"},
     "tables": {"asiakas": [{...}], "kontakti": [{...}, ...], "diagnoosi": [...], ...}}

Each table is the list of the patient's rows with the original column names and the types of the
table's ``*.schema.json`` (dates and decimals as strings, booleans as booleans, missing as null).
Tables with no rows for the patient are present as ``[]``. Nothing is added, renamed or derived, so
an organisation that maintains the real database can produce the same file with one query per
table (see ``SELECTIONS`` for how each table is tied to the patient).

Standard library only. Never logs or prints row contents.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "DUMP_FORMAT",
    "DUMP_VERSION",
    "TABLES",
    "dump_patient",
    "import_tables",
    "patient_ids",
]

DUMP_FORMAT: Final = "luvn-clinical-dump"
DUMP_VERSION: Final = 1

TABLES: Final = (
    "asiakas",
    "kontakti",
    "diagnoosi",
    "toimenpide",
    "laakitys",
    "laakitys_kontakti",
    "vastausarkistohistoria_view",
    "laboratorio_kontakti",
    "ajanvaraus",
    "osastohoitojakso",
)

# How a table is tied to one patient (`?` = the asiakas_id). The tables without an asiakas_id
# column join through a contact or through the table they describe.
SELECTIONS: Final[dict[str, str]] = {
    "asiakas": "asiakas_id = ?",
    "kontakti": "asiakas_id = ?",
    "diagnoosi": "asiakas_id = ?",
    "toimenpide": "kontakti_id IN (SELECT kontakti_id FROM kontakti WHERE asiakas_id = ?)",
    "laakitys": "asiakas_id = ?",
    "laakitys_kontakti": (
        "laakitys_avain IN (SELECT laakitys_avain FROM laakitys WHERE asiakas_id = ?)"
    ),
    "vastausarkistohistoria_view": "asiakas_id = ?",
    "laboratorio_kontakti": (
        "Avain IN (SELECT Avain FROM vastausarkistohistoria_view WHERE asiakas_id = ?)"
    ),
    "ajanvaraus": "asiakas_id = ?",
    "osastohoitojakso": "asiakas_id = ?",
}

_IDENT: Final = re.compile(r"^\w+$")


@dataclass(frozen=True)
class _Column:
    name: str
    boolean: bool
    sql_type: str


def _columns(schema_path: Path) -> list[_Column]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    columns = []
    for col in schema["columns"]:
        name, dtype = col["name"], col["dtype"]
        if not _IDENT.match(name):
            raise ValueError(f"unexpected column name in {schema_path.name}")
        sql_type = "INTEGER" if dtype.startswith(("Int", "UInt", "Boolean")) else "TEXT"
        columns.append(_Column(name, dtype == "Boolean", sql_type))
    return columns


def _jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:  # a zero-byte file (empty table) yields nothing
        for line in fh:
            if line.strip():
                yield json.loads(line)


def import_tables(tables_dir: Path, db_path: Path) -> dict[str, int]:
    """Load the LUVN ``clinical/tables`` JSONL files into a fresh SQLite file.

    Returns the row count per table. Column types come from the ``*.schema.json`` files; indexes
    are created on the columns the patient selections use.
    """
    if db_path.exists():
        db_path.unlink()
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE _boolean_columns (table_name TEXT, column_name TEXT)")
        for table in TABLES:
            columns = _columns(tables_dir / f"{table}.schema.json")
            con.executemany(
                "INSERT INTO _boolean_columns VALUES (?, ?)",
                [(table, c.name) for c in columns if c.boolean],
            )
            decl = ", ".join(f'"{c.name}" {c.sql_type}' for c in columns)
            con.execute(f'CREATE TABLE "{table}" ({decl})')
            marks = ", ".join("?" for _ in columns)
            sql = f'INSERT INTO "{table}" VALUES ({marks})'  # noqa: S608 - constant table name
            batch: list[tuple[Any, ...]] = []
            n = 0
            for row in _jsonl_rows(tables_dir / f"{table}.jsonl"):
                batch.append(tuple(_to_db(row.get(c.name), c) for c in columns))
                n += 1
                if len(batch) >= 5000:
                    con.executemany(sql, batch)
                    batch.clear()
            con.executemany(sql, batch)
            counts[table] = n
        for statement in (
            "CREATE INDEX ix_kontakti ON kontakti (asiakas_id)",
            "CREATE INDEX ix_kontakti_id ON kontakti (kontakti_id)",
            "CREATE INDEX ix_diagnoosi ON diagnoosi (asiakas_id)",
            "CREATE INDEX ix_toimenpide ON toimenpide (kontakti_id)",
            "CREATE INDEX ix_laakitys ON laakitys (asiakas_id)",
            "CREATE INDEX ix_laakitys_avain ON laakitys (laakitys_avain)",
            "CREATE INDEX ix_laakitys_kontakti ON laakitys_kontakti (laakitys_avain)",
            "CREATE INDEX ix_lab ON vastausarkistohistoria_view (asiakas_id)",
            "CREATE INDEX ix_lab_avain ON vastausarkistohistoria_view (Avain)",
            "CREATE INDEX ix_lab_kontakti ON laboratorio_kontakti (Avain)",
            "CREATE INDEX ix_ajanvaraus ON ajanvaraus (asiakas_id)",
            "CREATE INDEX ix_asiakas ON asiakas (asiakas_id)",
        ):
            con.execute(statement)
    return counts


def _to_db(value: Any, column: _Column) -> Any:
    if column.boolean and value is not None:
        return int(bool(value))
    return value


def patient_ids(db_path: Path) -> list[str]:
    """All ``asiakas_id`` values, in table order."""
    with sqlite3.connect(db_path) as con:
        return [r[0] for r in con.execute("SELECT asiakas_id FROM asiakas ORDER BY rowid")]


def dump_patient(
    con: sqlite3.Connection, asiakas_id: str, *, exported_at: dt.date | None = None
) -> dict[str, Any]:
    """The JSON-serialisable dump of one patient. Raises `KeyError` for an unknown patient."""
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:
        # Table names and selections are the constants above, never input.
        query = f'SELECT * FROM "{table}" WHERE {SELECTIONS[table]} ORDER BY rowid'  # noqa: S608
        cursor = con.execute(query, (asiakas_id,))
        names = [d[0] for d in cursor.description]
        bool_cols = _boolean_columns(con, table)
        tables[table] = [
            {
                n: (bool(v) if n in bool_cols and v is not None else v)
                for n, v in zip(names, row, strict=True)
            }
            for row in cursor
        ]
    if not tables["asiakas"]:
        raise KeyError("unknown patient")
    return {
        "meta": {
            "format": DUMP_FORMAT,
            "version": DUMP_VERSION,
            "exported_at": (exported_at or dt.date.today()).isoformat(),
        },
        "tables": tables,
    }


def _boolean_columns(con: sqlite3.Connection, table: str) -> frozenset[str]:
    """Columns that SQLite stores as 0/1 but the table schema declares Boolean."""
    rows = con.execute("SELECT column_name FROM _boolean_columns WHERE table_name = ?", (table,))
    return frozenset(r[0] for r in rows)
