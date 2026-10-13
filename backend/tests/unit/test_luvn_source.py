"""LUVN dump: tables -> SQLite -> per-patient JSON -> intermediate extraction, without an LLM.

All data is invented for these tests (two tiny patients in the LUVN table layout).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.pipeline.extractors import (
    ExtractorOutput,
    LuvnDumpExtractor,
    StructuredFirstExtractor,
)
from app.pipeline.ground import apply_grounding, ground
from app.pipeline.ingest import ingest
from app.pipeline.run import PipelineHooks, StepEvent, run_pipeline
from app.schemas.intermediate import (
    IpsExtraction,
    ItemsFound,
    MedicationItem,
    NoInformation,
)
from app.schemas.source import IngestedDocument
from app.sources.luvn.dump import (
    TABLES,
    PatientFilter,
    dump_patient,
    import_tables,
    patient_ids,
    select_patient_ids,
)
from app.sources.luvn.manifest import build_manifest, summarise
from app.sources.luvn.parse import LuvnDumpError, is_luvn_dump, parse_dump

EXPORTED = dt.date(2026, 10, 13)

COLUMNS: dict[str, list[tuple[str, str]]] = {
    "asiakas": [
        ("asiakas_id", "String"),
        ("henkilotunnus", "String"),
        ("kotikunta", "String"),
        ("sukupuoli", "String"),
        ("syntymavuosi", "Int32"),
        ("syntymapaiva", "Date"),
        ("kieli", "String"),
        ("onko_testiasiakas", "Boolean"),
    ],
    "kontakti": [("kontakti_id", "String"), ("asiakas_id", "String")],
    "diagnoosi": [
        ("diagnoosi_id", "String"),
        ("icd10_id", "String"),
        ("icd10_koodi_lahdejarjestelma", "String"),
        ("kontakti_id", "String"),
        ("asiakas_id", "String"),
        ("diagnoosi_aikaleima", "Datetime(time_unit='us', time_zone=None)"),
        ("diagnoosi_ensisijaisuus", "String"),
        ("onko_pitkaaikaisdiagnoosi", "Boolean"),
    ],
    "toimenpide": [("toimenpide_id", "String"), ("kontakti_id", "String")],
    "laakitys": [
        ("laakitys_avain", "String"),
        ("laakitys_aloituspvm", "Date"),
        ("laakitys_paattymispvm", "Date"),
        ("asiakas_id", "String"),
        ("on_resepti", "Boolean"),
        ("vaikuttava_aine", "String"),
        ("atc_koodi", "String"),
        ("laakkeen_kayttotapa", "String"),
    ],
    "laakitys_kontakti": [("laakitys_avain", "String"), ("kontakti_id", "String")],
    "vastausarkistohistoria_view": [
        ("Avain", "Int32"),
        ("asiakas_id", "String"),
        ("NumeerinenTutkimustulos", "Decimal(precision=18, scale=3)"),
        ("PaatutkimuksenLyhenne", "String"),
    ],
    "laboratorio_kontakti": [("Avain", "Int32"), ("kontakti_id", "String")],
    "ajanvaraus": [("ajanvaraus_id", "String"), ("asiakas_id", "String")],
    "osastohoitojakso": [("osastohoitojakso_id", "String"), ("asiakas_id", "String")],
}


def _asiakas(n: int, **over: Any) -> dict[str, Any]:
    return {
        "asiakas_id": f"SYN-ASI-{n}",
        "henkilotunnus": f"SYN-HEN-{n}",
        "kotikunta": "Espoo",
        "sukupuoli": "NAINEN",
        "syntymavuosi": 1980,
        "syntymapaiva": "1980-05-17",
        "kieli": "fi",
        "onko_testiasiakas": True,
        **over,
    }


def _diagnosis(
    n: int, patient: int, contact: int, code: str, when: str, long: bool
) -> dict[str, Any]:
    return {
        "diagnoosi_id": f"SYN-DX-{n}",
        "icd10_id": code,
        "icd10_koodi_lahdejarjestelma": code,
        "kontakti_id": f"SYN-CON-{contact}",
        "asiakas_id": f"SYN-ASI-{patient}",
        "diagnoosi_aikaleima": f"{when}T10:00:00.000000",
        "diagnoosi_ensisijaisuus": "P",
        "onko_pitkaaikaisdiagnoosi": long,
    }


def _medication(n: int, patient: int, active: bool, **over: Any) -> dict[str, Any]:
    return {
        "laakitys_avain": f"SYN-MED-{n}",
        "laakitys_aloituspvm": "2026-09-01",
        "laakitys_paattymispvm": "2026-12-31" if active else "2026-09-07",
        "asiakas_id": f"SYN-ASI-{patient}",
        "on_resepti": True,
        "vaikuttava_aine": "metformiini",
        "atc_koodi": "A10BA02",
        "laakkeen_kayttotapa": "SÄÄNNÖLLINEN",
        **over,
    }


ROWS: dict[str, list[dict[str, Any]]] = {
    "asiakas": [_asiakas(1), _asiakas(2, sukupuoli="MIES")],
    "kontakti": [
        {"kontakti_id": "SYN-CON-10", "asiakas_id": "SYN-ASI-1"},
        {"kontakti_id": "SYN-CON-11", "asiakas_id": "SYN-ASI-1"},
        {"kontakti_id": "SYN-CON-20", "asiakas_id": "SYN-ASI-2"},
    ],
    "diagnoosi": [
        _diagnosis(1, 1, 10, "E11.9", "2025-03-01", True),
        _diagnosis(2, 1, 11, "E11.9", "2024-02-01", False),
        _diagnosis(3, 1, 11, "J06.9", "2025-06-01", False),
        _diagnosis(4, 1, 11, "Z99.9", "2025-06-01", False),
        _diagnosis(5, 2, 20, "I10", "2025-01-01", False),
    ],
    "toimenpide": [
        {"toimenpide_id": "SYN-PROC-1", "kontakti_id": "SYN-CON-10"},
        {"toimenpide_id": "SYN-PROC-2", "kontakti_id": "SYN-CON-20"},
    ],
    "laakitys": [
        _medication(1, 1, True),
        _medication(
            2,
            1,
            False,
            vaikuttava_aine="parasetamoli",
            atc_koodi="N02BE01",
            laakkeen_kayttotapa="TARVITTAESSA",
            on_resepti=False,
        ),
        _medication(3, 2, True, atc_koodi=None),
    ],
    "laakitys_kontakti": [
        {"laakitys_avain": "SYN-MED-1", "kontakti_id": "SYN-CON-10"},
        {"laakitys_avain": "SYN-MED-2", "kontakti_id": "SYN-CON-11"},
        {"laakitys_avain": "SYN-MED-3", "kontakti_id": "SYN-CON-20"},
    ],
    "vastausarkistohistoria_view": [
        {
            "Avain": 1,
            "asiakas_id": "SYN-ASI-1",
            "NumeerinenTutkimustulos": "5.100",
            "PaatutkimuksenLyhenne": "B-HbA1c",
        },
        {
            "Avain": 2,
            "asiakas_id": "SYN-ASI-2",
            "NumeerinenTutkimustulos": "89.863",
            "PaatutkimuksenLyhenne": "P-Krea",
        },
    ],
    "laboratorio_kontakti": [
        {"Avain": 1, "kontakti_id": "SYN-CON-10"},
        {"Avain": 2, "kontakti_id": "SYN-CON-20"},
    ],
    "ajanvaraus": [
        {"ajanvaraus_id": "SYN-APT-1", "asiakas_id": "SYN-ASI-1"},
        {"ajanvaraus_id": "SYN-APT-2", "asiakas_id": "SYN-ASI-2"},
    ],
    "osastohoitojakso": [],
}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    tables = tmp_path / "tables"
    tables.mkdir()
    for table in TABLES:
        schema = {
            "schema_version": 1,
            "row_count": len(ROWS[table]),
            "columns": [{"name": n, "dtype": t} for n, t in COLUMNS[table]],
        }
        (tables / f"{table}.schema.json").write_text(json.dumps(schema), encoding="utf-8")
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ROWS[table])
        (tables / f"{table}.jsonl").write_text(text, encoding="utf-8")  # empty table: zero bytes
    path = tmp_path / "luvn.db"
    counts = import_tables(tables, path)
    assert counts["asiakas"] == 2
    assert counts["osastohoitojakso"] == 0
    return path


def _dump(db: Path, asiakas_id: str) -> dict[str, Any]:
    with sqlite3.connect(db) as con:
        return dump_patient(con, asiakas_id, exported_at=EXPORTED)


def _parse(dump: dict[str, Any]) -> tuple[IpsExtraction, IngestedDocument, bytes]:
    data = json.dumps(dump, ensure_ascii=False).encode()
    doc = ingest(data, "application/json")
    return parse_dump(dump, doc), doc, data


# ---- dump -----------------------------------------------------------------------------------


def test_dump_is_the_patients_rows_per_table(db: Path) -> None:
    dump = _dump(db, "SYN-ASI-1")
    assert dump["meta"] == {
        "format": "luvn-clinical-dump",
        "version": 1,
        "exported_at": "2026-10-13",
    }
    assert list(dump["tables"]) == list(TABLES)
    t = dump["tables"]
    assert [r["icd10_id"] for r in t["diagnoosi"]] == ["E11.9", "E11.9", "J06.9", "Z99.9"]
    assert [r["laakitys_avain"] for r in t["laakitys"]] == ["SYN-MED-1", "SYN-MED-2"]
    # tables without an asiakas_id column are selected through the contact / the parent table
    assert [r["toimenpide_id"] for r in t["toimenpide"]] == ["SYN-PROC-1"]
    assert [r["laakitys_avain"] for r in t["laakitys_kontakti"]] == ["SYN-MED-1", "SYN-MED-2"]
    assert [r["Avain"] for r in t["laboratorio_kontakti"]] == [1]
    assert t["osastohoitojakso"] == []
    assert t["vastausarkistohistoria_view"][0]["NumeerinenTutkimustulos"] == "5.100"


def test_dump_keeps_types_and_nulls(db: Path) -> None:
    dump = _dump(db, "SYN-ASI-2")
    assert dump["tables"]["asiakas"][0]["onko_testiasiakas"] is True
    assert dump["tables"]["asiakas"][0]["syntymavuosi"] == 1980
    assert dump["tables"]["laakitys"][0]["on_resepti"] is True
    assert dump["tables"]["laakitys"][0]["atc_koodi"] is None
    assert dump["tables"]["diagnoosi"][0]["onko_pitkaaikaisdiagnoosi"] is False


def test_dump_unknown_patient(db: Path) -> None:
    with sqlite3.connect(db) as con, pytest.raises(KeyError):
        dump_patient(con, "SYN-ASI-404")


def test_patient_ids(db: Path) -> None:
    assert patient_ids(db) == ["SYN-ASI-1", "SYN-ASI-2"]


# ---- parser ---------------------------------------------------------------------------------


def test_parse_patient(db: Path) -> None:
    extraction, _, _ = _parse(_dump(db, "SYN-ASI-1"))
    p = extraction.patient
    assert extraction.document_language == "fi"
    assert p.names == []
    assert p.birth_date is not None
    assert p.birth_date.value == "1980-05-17"
    assert p.birth_date.locator == "$.tables.asiakas[0].syntymapaiva"
    assert p.gender is not None
    assert p.gender.value.value == "female"
    assert [(i.type_text, i.value) for i in p.identifiers] == [
        ("asiakas_id", "SYN-ASI-1"),
        ("henkilotunnus", "SYN-HEN-1"),
    ]


def test_parse_medications(db: Path) -> None:
    extraction, _, _ = _parse(_dump(db, "SYN-ASI-1"))
    section = extraction.medications
    assert isinstance(section, ItemsFound)
    first, second = section.items
    assert isinstance(first, MedicationItem)
    assert (first.medication_text, first.printed_code, first.printed_code_system_text) == (
        "metformiini",
        "A10BA02",
        "ATC",
    )
    assert first.status.value == "active"
    assert not first.dosage.as_needed
    assert second.status.value == "completed"
    assert second.dosage.as_needed
    assert (second.effective_start, second.effective_end) == ("2026-09-01", "2026-09-07")
    assert first.locator == "$.tables.laakitys[0].vaikuttava_aine"


def test_parse_medication_without_atc_code(db: Path) -> None:
    extraction, _, _ = _parse(_dump(db, "SYN-ASI-2"))
    assert isinstance(extraction.medications, ItemsFound)
    (item,) = extraction.medications.items
    assert item.printed_code is None
    assert item.printed_code_system_text is None


def test_parse_problems_one_per_code(db: Path) -> None:
    extraction, _, _ = _parse(_dump(db, "SYN-ASI-1"))
    assert isinstance(extraction.problems, ItemsFound)
    by_code = {i.printed_code: i for i in extraction.problems.items}
    assert list(by_code) == ["E11.9", "J06.9", "Z99.9"]
    diabetes = by_code["E11.9"]
    assert diabetes.condition_text == "Aikuistyypin diabetes ilman komplikaatioita"
    assert diabetes.clinical_status.value == "active"  # a long-term diagnosis
    assert diabetes.onset == "2024-02-01"  # earliest of its rows
    assert by_code["J06.9"].clinical_status.value == "not_stated"
    assert by_code["Z99.9"].condition_text == "ICD-10 Z99.9"  # no known display name
    assert by_code["E11.9"].printed_code_system_text == "ICD-10"


def test_allergies_are_never_none_known(db: Path) -> None:
    extraction, _, _ = _parse(_dump(db, "SYN-ASI-1"))
    assert isinstance(extraction.allergies, NoInformation)


def test_empty_tables_give_no_information(db: Path) -> None:
    dump = _dump(db, "SYN-ASI-1")
    dump["tables"]["laakitys"] = []
    dump["tables"]["diagnoosi"] = []
    extraction, _, _ = _parse(dump)
    assert isinstance(extraction.medications, NoInformation)
    assert isinstance(extraction.problems, NoInformation)


def test_every_quote_grounds_exactly(db: Path) -> None:
    extraction, doc, _ = _parse(_dump(db, "SYN-ASI-1"))
    report = ground(extraction, doc)
    grounded = apply_grounding(extraction, report)
    assert not grounded.dropped
    assert not grounded.flags
    counts = {status.value: n for status, n in report.counts.items() if n}
    assert list(counts) == ["exact"]


def test_printed_codes_sit_inside_their_quotes(db: Path) -> None:
    extraction, _, _ = _parse(_dump(db, "SYN-ASI-1"))
    assert isinstance(extraction.medications, ItemsFound)
    for item in extraction.medications.items:
        assert item.printed_code
        assert item.printed_code in item.source_quote


def test_parse_rejects_other_json() -> None:
    others: list[object] = [{"resourceType": "Bundle"}, {"meta": {"format": "other"}}, []]
    for value in others:
        assert not is_luvn_dump(value)
    bad = {"meta": {"format": "luvn-clinical-dump", "version": 99}, "tables": {}}
    doc = ingest(json.dumps(bad).encode(), "application/json")
    with pytest.raises(LuvnDumpError):
        parse_dump(bad, doc)
    two = {"meta": bad["meta"] | {"version": 1}, "tables": {"asiakas": [{}, {}]}}
    with pytest.raises(LuvnDumpError):
        parse_dump(two, ingest(json.dumps(two).encode(), "application/json"))


# ---- extractor routing and the whole pipeline -----------------------------------------------


class _Fallback:
    name = "fallback"

    def __call__(self, data: bytes, doc: IngestedDocument) -> ExtractorOutput:
        raise AssertionError("the fallback must not be used for a LUVN dump")


def test_structured_first_extractor_parses_dumps(db: Path) -> None:
    _, doc, data = _parse(_dump(db, "SYN-ASI-1"))
    output = StructuredFirstExtractor(_Fallback())(data, doc)
    assert output.model == "luvn-dump-parser"
    assert output.prompt_version is None


def test_structured_first_extractor_leaves_other_documents_alone() -> None:
    data = json.dumps({"patient": "Testi Potilas"}).encode()
    doc = ingest(data, "application/json")
    assert not LuvnDumpExtractor.accepts(data, doc)
    with pytest.raises(AssertionError):
        StructuredFirstExtractor(_Fallback())(data, doc)


def test_pipeline_end_to_end_without_llm(db: Path) -> None:
    _, _, data = _parse(_dump(db, "SYN-ASI-1"))
    events: list[StepEvent] = []
    result = run_pipeline(
        data,
        "application/json",
        extractor=StructuredFirstExtractor(_Fallback()),
        on_event=events.append,
        hooks=PipelineHooks(),
        now=dt.datetime(2026, 10, 13, tzinfo=dt.UTC),
    )
    assert result.extractor_model == "luvn-dump-parser"
    assert not result.dropped
    assert not result.flags
    assert result.grounding_counts["exact"] > 0
    assert result.grounding_counts["not_found"] == 0


# ---- patient filters and manifest -----------------------------------------------------------


def _ids(db: Path, **kwargs: Any) -> list[str]:
    with sqlite3.connect(db) as con:
        return select_patient_ids(con, PatientFilter(**kwargs), exported_at=EXPORTED)


def test_no_filter_selects_everyone(db: Path) -> None:
    assert _ids(db) == ["SYN-ASI-1", "SYN-ASI-2"]


def test_filters_select_on_the_database(db: Path) -> None:
    assert _ids(db, with_labs=True) == ["SYN-ASI-1", "SYN-ASI-2"]
    assert _ids(db, has_long_term_dx=True) == ["SYN-ASI-1"]
    assert _ids(db, with_procedures=True) == ["SYN-ASI-1", "SYN-ASI-2"]
    # patient 1's medications: one ends 2026-12-31, patient 2's also: both active on the export date
    assert _ids(db, active_meds=True) == ["SYN-ASI-1", "SYN-ASI-2"]
    assert _ids(db, has_long_term_dx=True, ids=("SYN-ASI-2",)) == []
    assert _ids(db, ids=("SYN-ASI-2",)) == ["SYN-ASI-2"]


def test_active_meds_respects_the_export_date(db: Path) -> None:
    with sqlite3.connect(db) as con:
        later = select_patient_ids(
            con, PatientFilter(active_meds=True), exported_at=dt.date(2027, 6, 1)
        )
    assert later == []


def test_random_seed_is_reproducible(db: Path) -> None:
    assert _ids(db, random_seed=3) == _ids(db, random_seed=3)
    assert sorted(_ids(db, random_seed=3)) == ["SYN-ASI-1", "SYN-ASI-2"]


def test_summary_counts_and_score(db: Path) -> None:
    s = summarise(_dump(db, "SYN-ASI-1"))
    assert s["asiakas_id"] == "SYN-ASI-1"
    assert s["counts"] == {
        "problems": 3,
        "long_term_problems": 1,
        "medications": 2,
        "active_medications": 1,
    }
    assert s["ips_sections"] == ["problems", "medications"]
    assert s["not_mapped"] == {"lab_results": 1, "procedures": 1, "encounters": 2}
    assert s["score"] == 3 + 1 + 5


def test_summary_agrees_with_the_parser(db: Path) -> None:
    for asiakas_id in ("SYN-ASI-1", "SYN-ASI-2"):
        dump = _dump(db, asiakas_id)
        extraction, _, _ = _parse(dump)
        counts = summarise(dump)["counts"]
        assert isinstance(extraction.problems, ItemsFound)
        assert isinstance(extraction.medications, ItemsFound)
        assert counts["problems"] == len(extraction.problems.items)
        assert counts["medications"] == len(extraction.medications.items)
        active = [m for m in extraction.medications.items if m.status.value == "active"]
        assert counts["active_medications"] == len(active)


def test_summary_of_an_empty_patient(db: Path) -> None:
    dump = _dump(db, "SYN-ASI-1")
    dump["tables"]["laakitys"] = []
    dump["tables"]["diagnoosi"] = []
    s = summarise(dump)
    assert s["score"] == 0
    assert s["ips_sections"] == []


def test_manifest_is_sorted_best_first(db: Path) -> None:
    entries = [{"file": f"{i}.json", **summarise(_dump(db, i))} for i in ("SYN-ASI-2", "SYN-ASI-1")]
    manifest = build_manifest(entries, exported_at=EXPORTED, filters={"with_labs": True})
    assert manifest["meta"]["format"] == "luvn-dump-manifest"
    assert manifest["meta"]["filters"] == {"with_labs": True}
    scores = [p["score"] for p in manifest["patients"]]
    assert scores == sorted(scores, reverse=True)
    assert manifest["patients"][0]["asiakas_id"] == "SYN-ASI-1"
    # ids and counts only: no row contents
    assert "1980-05-17" not in json.dumps(manifest)


def test_cli_writes_dumps_and_manifest(db: Path, tmp_path: Path) -> None:
    from scripts.luvn_dump import main

    out = tmp_path / "out"
    args = ["dump", str(db), str(out), "--has-long-term-dx", "--exported-at", "2026-10-13"]
    assert main(args) == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["SYN-ASI-1.json", "manifest.json"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [p["file"] for p in manifest["patients"]] == ["SYN-ASI-1.json"]
    assert is_luvn_dump(json.loads((out / "SYN-ASI-1.json").read_text(encoding="utf-8")))
    # the limit and the minimum score apply after the database filters
    assert main(["dump", str(db), str(tmp_path / "o2"), "--min-score", "99"]) == 1
    assert main(["dump", str(db), str(tmp_path / "o3"), "--limit", "1"]) == 0
    assert len(json.loads((tmp_path / "o3/manifest.json").read_text())["patients"]) == 1
