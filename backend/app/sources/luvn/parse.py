"""Deterministic reader: LUVN patient dump (see `dump`) -> `IpsExtraction`, no LLM.

Mapping (one rule per field, nothing inferred beyond it):

* ``asiakas`` -> patient: ``syntymapaiva`` birth date, ``sukupuoli`` gender (MIES/NAINEN),
  ``asiakas_id`` and ``henkilotunnus`` identifiers, ``kieli`` document language. The tables hold no
  name, so ``asiakas_id`` stands in as the patient's name (the clinician can edit it in review).
* ``laakitys`` -> one medication per row: ``vaikuttava_aine`` name, ``atc_koodi`` printed code
  (hint only, D-9), dates, ``TARVITTAESSA`` = as needed. Active when the end date is not before the
  export date, else completed.
* ``diagnoosi`` -> one problem per distinct ``icd10_id``: earliest ``diagnoosi_aikaleima`` date as
  onset, active when any row is a long-term diagnosis, else status not stated.
* Allergies: the tables have none, so the section is ``no_information`` (never "none known").
* Not mapped yet (no intermediate-schema section): ``vastausarkistohistoria_view`` (results),
  ``toimenpide`` (procedures), ``kontakti`` and the rest.

Every fact quotes the ingested JSON leaf text of its key field (and the adjacent code leaf, so the
printed code is inside the quote) and points at that leaf with the ingest locator, so grounding
and the review UI work as for any JSON document. Quotes come from the `IngestedDocument`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from app.schemas.intermediate import IpsExtraction
from app.schemas.source import IngestedDocument
from app.sources.luvn.dump import DUMP_FORMAT, DUMP_VERSION
from app.sources.luvn.icd10_fi import ICD10_FI

__all__ = ["LuvnDumpError", "is_luvn_dump", "parse_dump"]

_GENDERS: Final = {"MIES": "male", "NAINEN": "female"}


class LuvnDumpError(ValueError):
    """The JSON is not a usable LUVN dump. Messages are fixed strings (no PHI)."""


def is_luvn_dump(value: object) -> bool:
    meta = value.get("meta") if isinstance(value, dict) else None
    return isinstance(meta, dict) and meta.get("format") == DUMP_FORMAT


def parse_dump(dump: dict[str, Any], doc: IngestedDocument) -> IpsExtraction:
    """Fill the intermediate schema from a dump; ``doc`` is the same JSON, ingested."""
    if not is_luvn_dump(dump):
        raise LuvnDumpError("not a LUVN clinical dump")
    if dump["meta"].get("version") != DUMP_VERSION:
        raise LuvnDumpError("unsupported LUVN dump version")
    tables = dump.get("tables")
    if not isinstance(tables, dict) or len(tables.get("asiakas") or []) != 1:
        raise LuvnDumpError("a dump holds exactly one asiakas row")
    exported = _date(dump["meta"].get("exported_at")) or dt.date.today()
    quoter = _Quoter(doc)
    client = tables["asiakas"][0]
    return IpsExtraction.model_validate(
        {
            "document_language": client.get("kieli") or "fi",
            "patient": _patient(client, quoter),
            "allergies": {"kind": "no_information"},
            "medications": _medications(tables.get("laakitys") or [], exported, quoter),
            "problems": _problems(tables.get("diagnoosi") or [], quoter),
        }
    )


class _Quoter:
    """Source quote and locator of JSON leaves, taken from the ingested document."""

    def __init__(self, doc: IngestedDocument) -> None:
        self._doc = doc

    def at(self, table: str, index: int, *columns: str) -> dict[str, Any]:
        """Fact location for the first column; the quote also covers any further adjacent ones."""
        locators = [f"$.tables.{table}[{index}].{c}" for c in columns]
        segments = [self._doc.find_segment(1, loc) for loc in locators]
        texts = [s.text for s in segments if s is not None]
        if segments[0] is None or len(texts) != len(segments):
            raise LuvnDumpError("dump row does not match the ingested document")
        return {
            "source_quote": "\n".join(texts),
            "page": 1,
            "locator": locators[0],
            "confidence": "high",
        }


def _date(value: object) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _patient(client: dict[str, Any], quote: _Quoter) -> dict[str, Any]:
    identifiers = [
        {
            **quote.at("asiakas", 0, column),
            "value": str(client[column]),
            "type_text": label,
            "issuer_text": "",
        }
        for column, label in (("asiakas_id", "asiakas_id"), ("henkilotunnus", "henkilotunnus"))
        if client.get(column)
    ]
    birth_date = (
        {**quote.at("asiakas", 0, "syntymapaiva"), "value": client["syntymapaiva"]}
        if _date(client.get("syntymapaiva"))
        else None
    )
    gender = _GENDERS.get(str(client.get("sukupuoli")))
    names = (
        [
            {
                **quote.at("asiakas", 0, "asiakas_id"),
                "text": str(client["asiakas_id"]),
                "family": "",
                "given": [],
            }
        ]
        if client.get("asiakas_id")
        else []
    )
    return {
        "names": names,
        "birth_date": birth_date,
        "gender": {**quote.at("asiakas", 0, "sukupuoli"), "value": gender} if gender else None,
        "identifiers": identifiers,
    }


def _medications(rows: list[dict[str, Any]], exported: dt.date, quote: _Quoter) -> dict[str, Any]:
    items = []
    for i, row in enumerate(rows):
        name = row.get("vaikuttava_aine")
        if not name:
            continue
        code = row.get("atc_koodi")
        end = _date(row.get("laakitys_paattymispvm"))
        items.append(
            {
                **quote.at("laakitys", i, "vaikuttava_aine", *(["atc_koodi"] if code else [])),
                "medication_text": name,
                "printed_code": code or "",
                "printed_code_system_text": "ATC" if code else "",
                "strength_text": "",
                "dose_form_text": "",
                "dosage": {
                    "text": "",
                    "dose_value": "",
                    "dose_unit": "",
                    "frequency": "",
                    "period": "",
                    "period_unit": "not_stated",
                    "as_needed": row.get("laakkeen_kayttotapa") == "TARVITTAESSA",
                    "route_text": "",
                },
                "status": "completed" if end is not None and end < exported else "active",
                "effective_start": row.get("laakitys_aloituspvm") or "",
                "effective_end": row.get("laakitys_paattymispvm") or "",
                "reason_text": "",
                "note": "",
            }
        )
    return {"kind": "items_found", "items": items} if items else {"kind": "no_information"}


def _problems(rows: list[dict[str, Any]], quote: _Quoter) -> dict[str, Any]:
    first: dict[str, int] = {}
    onset: dict[str, str] = {}
    long_term: set[str] = set()
    for i, row in enumerate(rows):
        code = row.get("icd10_id")
        if not code:
            continue
        first.setdefault(code, i)
        when = str(row.get("diagnoosi_aikaleima") or "")[:10]
        if when and (code not in onset or when < onset[code]):
            onset[code] = when
        if row.get("onko_pitkaaikaisdiagnoosi"):
            long_term.add(code)
    items = [
        {
            **quote.at("diagnoosi", i, "icd10_id"),
            "condition_text": ICD10_FI.get(code, f"ICD-10 {code}"),
            "printed_code": code,
            "printed_code_system_text": "ICD-10",
            "clinical_status": "active" if code in long_term else "not_stated",
            "verification_status": "not_stated",
            "severity": "not_stated",
            "body_site_text": "",
            "onset": onset.get(code, ""),
            "abatement": "",
            "note": "",
        }
        for code, i in first.items()
    ]
    return {"kind": "items_found", "items": items} if items else {"kind": "no_information"}
