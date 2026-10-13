"""What is in a patient dump, from the IPS point of view (`manifest.json`).

`summarise` counts the rows that matter for the IPS and gives a score; `build_manifest` collects the
summaries of a dump run, best first, so the interesting files are easy to find. Pure functions over
the dump dict; no I/O, no row contents in the output (ids and counts only).

Score (higher = more to review): ``min(problems, 10) + min(active_medications, 10)`` plus 5 when the
patient has a long-term diagnosis. Only what `parse` maps counts; labs, procedures and encounters
are listed as present-but-not-mapped and do not score. Allergies are always empty and not scored.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

__all__ = ["MANIFEST_FORMAT", "MANIFEST_VERSION", "build_manifest", "summarise"]

MANIFEST_FORMAT: Final = "luvn-dump-manifest"
MANIFEST_VERSION: Final = 1
_CAP: Final = 10
_LONG_TERM_BONUS: Final = 5
SCORING: Final = (
    "min(problems,10) + min(active_medications,10) + 5 if long_term_problems > 0; "
    "labs, procedures, encounters are not mapped to IPS sections yet and do not score"
)


def _date(value: object) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def summarise(dump: dict[str, Any]) -> dict[str, Any]:
    """Counts, IPS sections that can be filled and the score of one dump."""
    tables = dump["tables"]
    exported = _date(dump["meta"].get("exported_at")) or dt.date.today()
    diagnoses = [r for r in tables.get("diagnoosi", []) if r.get("icd10_id")]
    problems = {r["icd10_id"] for r in diagnoses}
    long_term = {r["icd10_id"] for r in diagnoses if r.get("onko_pitkaaikaisdiagnoosi")}
    medications = [r for r in tables.get("laakitys", []) if r.get("vaikuttava_aine")]
    active = [
        r
        for r in medications
        if (end := _date(r.get("laakitys_paattymispvm"))) is None or end >= exported
    ]
    sections = [
        name for name, n in (("problems", len(problems)), ("medications", len(medications))) if n
    ]
    score = (
        min(len(problems), _CAP) + min(len(active), _CAP) + (_LONG_TERM_BONUS if long_term else 0)
    )
    return {
        "asiakas_id": tables["asiakas"][0]["asiakas_id"],
        "score": score,
        "ips_sections": sections,
        "counts": {
            "problems": len(problems),
            "long_term_problems": len(long_term),
            "medications": len(medications),
            "active_medications": len(active),
        },
        "not_mapped": {
            "lab_results": len(tables.get("vastausarkistohistoria_view", [])),
            "procedures": len(tables.get("toimenpide", [])),
            "encounters": len(tables.get("kontakti", [])),
        },
    }


def build_manifest(
    entries: list[dict[str, Any]], *, exported_at: dt.date, filters: dict[str, Any]
) -> dict[str, Any]:
    """``entries`` are `summarise` results plus a ``file`` name; sorted best first, then by id."""
    ordered = sorted(entries, key=lambda e: (-e["score"], e["asiakas_id"]))
    return {
        "meta": {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "exported_at": exported_at.isoformat(),
            "filters": filters,
            "scoring": SCORING,
        },
        "patients": ordered,
    }
