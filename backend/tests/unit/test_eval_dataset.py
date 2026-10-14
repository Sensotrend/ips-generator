"""Consistency checks for the Phase 1 eval dataset (``evals/dataset/``).

Every case's gold must be a valid ``IpsExtraction`` whose quotes ground ``exact`` or
``normalised`` at their stated page/locator in the ingested document, its feature tags must hold
where they can be checked mechanically, and the dataset as a whole must cover the required
languages, formats, document types and features.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from app.pipeline.ground import GroundingStatus, apply_grounding, ground, iter_facts
from app.pipeline.ingest import ingest
from app.schemas.intermediate import (
    AllergiesFound,
    AllergyCategory,
    AllergyItem,
    AllergyScope,
    AllergyType,
    ConditionClinicalStatus,
    ConditionItem,
    ConditionVerificationStatus,
    IpsExtraction,
    ItemsFound,
    MedicationItem,
    MedicationStatus,
    NoInformation,
    NoKnownAllergies,
    NoneKnown,
)
from app.schemas.source import IngestedDocument

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET = REPO_ROOT / "evals" / "dataset"
CASE_DIRS = sorted(p for p in DATASET.iterdir() if (p / "meta.json").is_file())
CASE_IDS = [p.name for p in CASE_DIRS]

MEDIA_TYPES = {
    "txt": "text/plain",
    "json": "application/json",
    "csv": "text/csv",
    "pdf": "application/pdf",
}
LANGUAGES = {"fi", "sv", "en", "fi+sv", "fi+en"}
DOC_TYPES = {
    "discharge_summary",
    "referral_letter",
    "prescription",
    "medication_list",
    "lab_report",
    "outpatient_note",
}
META_KEYS = {
    "case_id",
    "language",
    "format",
    "media_type",
    "doc_type",
    "features",
    "notes",
    "expected_patient",
}
REQUIRED_FEATURES = {
    "nkda_plus_food_allergy",
    "none_known_allergies",
    "section_no_information",
    "no_regular_medication",
    "printed_icd10",
    "printed_atc",
    "resolved_condition",
    "family_history_distractor",
    "duplicated_medication",
    "stopped_medication",
    "paused_medication",
    "as_needed_dosing",
    "partial_dates",
    "abbreviations",
    "typos",
    "prompt_injection",
    "other_person_mentioned",
    "hetu_without_birth_date",
    "lab_report_all_no_information",
    "multi_page_pdf",
    "mostly_empty_page",
    "mixed_language",
    "caps_headings",
    "messy_formatting",
    "decimal_comma",
}

_HETU = re.compile(r"(?<![\w-])(\d{6})([-+A-FU-Y])(\d{3})([0-9A-Y])(?!\w)")
_HETU_CHECK = "0123456789ABCDEFHJKLMNPRSTUVWXY"


# ---- loading ------------------------------------------------------------------------------


@cache
def _meta(case_id: str) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads((DATASET / case_id / "meta.json").read_text("utf-8"))
    return meta


@cache
def _gold(case_id: str) -> IpsExtraction:
    return IpsExtraction.model_validate_json((DATASET / case_id / "gold.json").read_bytes())


def _document_path(case_id: str) -> Path:
    return DATASET / case_id / f"document.{_meta(case_id)['format']}"


@cache
def _doc(case_id: str) -> IngestedDocument:
    return ingest(_document_path(case_id).read_bytes(), _meta(case_id)["media_type"])


def _allergy_items(gold: IpsExtraction) -> list[AllergyItem]:
    return list(gold.allergies.items) if isinstance(gold.allergies, AllergiesFound) else []


def _medication_items(gold: IpsExtraction) -> list[MedicationItem]:
    return list(gold.medications.items) if isinstance(gold.medications, ItemsFound) else []


def _condition_items(gold: IpsExtraction) -> list[ConditionItem]:
    return list(gold.problems.items) if isinstance(gold.problems, ItemsFound) else []


# ---- per case -----------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_meta_is_well_formed(case_id: str) -> None:
    meta = _meta(case_id)
    assert set(meta) - {"extra_sections"} == META_KEYS
    assert meta.get("extra_sections", True) is True
    assert meta["case_id"] == case_id
    assert meta["language"] in LANGUAGES
    assert meta["format"] in MEDIA_TYPES
    assert meta["media_type"] == MEDIA_TYPES[meta["format"]]
    assert meta["doc_type"] in DOC_TYPES
    assert isinstance(meta["features"], list)
    assert len(set(meta["features"])) == len(meta["features"])
    assert all(isinstance(f, str) and f for f in meta["features"])
    assert isinstance(meta["notes"], str)
    assert meta["notes"].strip()
    assert _document_path(case_id).is_file()
    assert sorted(p.name for p in (DATASET / case_id).iterdir()) == sorted(
        [_document_path(case_id).name, "gold.json", "meta.json"]
    )


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_gold_is_valid_and_grounded(case_id: str) -> None:
    gold = _gold(case_id)
    doc = _doc(case_id)
    assert gold.document_language == _meta(case_id)["language"].split("+")[0]
    report = ground(gold, doc)
    assert report.facts, "every case has at least one fact (a patient detail or statement)"
    not_verbatim = [
        (f.path, f.status)
        for f in report.facts
        if f.status not in (GroundingStatus.EXACT, GroundingStatus.NORMALISED)
    ]
    assert not not_verbatim
    # No printed code outside its quote, nothing relocated or dropped.
    assert apply_grounding(gold, report).flags == ()


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_only_synthetic_hetus(case_id: str) -> None:
    texts = [_doc(case_id).full_text, (DATASET / case_id / "gold.json").read_text("utf-8")]
    for text in texts:
        for match in _HETU.finditer(text):
            birth, _century, individual, check = match.groups()
            assert int(individual) >= 900, "HETU outside the synthetic range 900-999"
            assert _HETU_CHECK[int(birth + individual) % 31] == check


_CENTURIES = {"+": 1800, **dict.fromkeys("-YXWVU", 1900), **dict.fromkeys("ABCDEF", 2000)}


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_expected_patient_is_the_truth(case_id: str) -> None:
    """``expected_patient`` (D-10) = stated values; for HETU-only cases the birth date encoded in
    the HETU, decoded here independently of ``app.pipeline.derive``. Never a gender from a
    900-999 code."""
    gold = _gold(case_id)
    expected = _meta(case_id)["expected_patient"]
    assert set(expected) == {"birth_date", "gender"}
    from_codes = set()
    for identifier in gold.patient.identifiers:
        match = _HETU.fullmatch(identifier.value)
        if match:
            ddmmyy, sign, _individual, _check = match.groups()
            year = _CENTURIES[sign] + int(ddmmyy[4:])
            from_codes.add(f"{year:04d}-{ddmmyy[2:4]}-{ddmmyy[:2]}")
    assert len(from_codes) <= 1
    if gold.patient.birth_date is not None:
        assert expected["birth_date"] == gold.patient.birth_date.value
        assert not from_codes or from_codes == {gold.patient.birth_date.value}
    else:
        assert expected["birth_date"] == next(iter(from_codes), None)
    assert expected["gender"] == (gold.patient.gender.value if gold.patient.gender else None)


def _has_partial_date(gold: IpsExtraction) -> bool:
    dates: list[str | None] = [gold.patient.birth_date.value if gold.patient.birth_date else None]
    dates += [a.onset for a in _allergy_items(gold)]
    dates += [d for m in _medication_items(gold) for d in (m.effective_start, m.effective_end)]
    dates += [d for c in _condition_items(gold) for d in (c.onset, c.abatement)]
    return any(d is not None and len(d) in (4, 7) for d in dates)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_checkable_features_hold(case_id: str) -> None:
    meta = _meta(case_id)
    features = set(meta["features"])
    gold = _gold(case_id)
    doc = _doc(case_id)
    allergies = _allergy_items(gold)
    medications = _medication_items(gold)
    conditions = _condition_items(gold)
    sections = (gold.allergies, gold.medications, gold.problems)
    past = {
        ConditionClinicalStatus.RESOLVED,
        ConditionClinicalStatus.INACTIVE,
        ConditionClinicalStatus.REMISSION,
    }

    checks = {
        "none_known_allergies": isinstance(gold.allergies, NoKnownAllergies),
        "nkda_plus_food_allergy": isinstance(gold.allergies, AllergiesFound)
        and any(s.scope is AllergyScope.MEDICATION for s in gold.allergies.none_known_statements)
        and any(a.category is AllergyCategory.FOOD for a in allergies),
        "no_regular_medication": isinstance(gold.medications, NoneKnown),
        "regular_none_plus_new_course": bool(medications),
        "section_no_information": any(isinstance(s, NoInformation) for s in sections),
        "lab_report_all_no_information": meta["doc_type"] == "lab_report"
        and all(isinstance(s, NoInformation) for s in sections),
        "printed_icd10": any(c.printed_code for c in conditions),
        "printed_atc": any(m.printed_code for m in medications),
        "resolved_condition": any(c.clinical_status in past for c in conditions)
        and any(c.clinical_status not in past for c in conditions),
        "stopped_medication": any(
            m.status in (MedicationStatus.STOPPED, MedicationStatus.COMPLETED) for m in medications
        ),
        "paused_medication": any(m.status is MedicationStatus.ON_HOLD for m in medications),
        "as_needed_dosing": any(m.dosage.as_needed for m in medications),
        "partial_dates": _has_partial_date(gold),
        "hetu_without_birth_date": gold.patient.birth_date is None
        and any(_HETU.fullmatch(i.value) for i in gold.patient.identifiers),
        "birth_date_stated": gold.patient.birth_date is not None,
        "gender_stated": gold.patient.gender is not None,
        "multi_page_pdf": meta["format"] == "pdf" and doc.page_count >= 2,
        "mostly_empty_page": meta["format"] == "pdf"
        and any(
            len(doc.page_text(p).strip()) < 40 or p in doc.pages_without_text
            for p in range(1, doc.page_count + 1)
        ),
        "mixed_language": "+" in meta["language"],
        "multi_segment_quote": any(
            "\n" in getattr(f, "source_quote", "") for _, f in iter_facts(gold)
        ),
        "allergy_reactions": any(a.reactions for a in allergies),
        "intolerance": any(a.type is AllergyType.INTOLERANCE for a in allergies),
        "suspected_condition": any(
            c.verification_status
            in (ConditionVerificationStatus.PROVISIONAL, ConditionVerificationStatus.DIFFERENTIAL)
            for c in conditions
        ),
    }
    failing = sorted(f for f in features & set(checks) if not checks[f])
    assert not failing, f"feature tags not reflected in gold/document: {failing}"
    # Two tags are also checked the other way round, as they describe the whole case.
    assert ("multi_page_pdf" in features) == checks["multi_page_pdf"]
    assert ("mixed_language" in features) == checks["mixed_language"]


# ---- whole dataset ------------------------------------------------------------------------


def test_dataset_coverage() -> None:
    metas = [_meta(c) for c in CASE_IDS]
    assert len(metas) >= 24

    languages = Counter(m["language"] for m in metas)
    assert languages["fi"] >= 10
    assert languages["sv"] >= 5
    assert languages["en"] >= 5
    assert languages["fi+sv"] + languages["fi+en"] >= 2

    formats = Counter(m["format"] for m in metas)
    assert set(formats) == set(MEDIA_TYPES)
    assert Counter(m["doc_type"] for m in metas).keys() == DOC_TYPES

    features = Counter(f for m in metas for f in m["features"])
    assert set(features) >= REQUIRED_FEATURES, REQUIRED_FEATURES - set(features)
    assert features["multi_page_pdf"] >= 2

    csv_delimiters = {
        _document_path(c).read_text("utf-8").split("\n", 1)[0].count(";") > 0
        for c in CASE_IDS
        if _meta(c)["format"] == "csv"
    }
    assert csv_delimiters == {True, False}, "need CSVs with both ';' and ',' delimiters"


def test_readme_lists_every_case() -> None:
    readme = (DATASET / "README.md").read_text("utf-8")
    missing = [c for c in CASE_IDS if f"`{c}`" not in readme]
    assert not missing


def test_extra_sections_cases_annotate_the_optional_sections() -> None:
    """``extra_sections: true`` cases carry facts for the optional sections, the others none."""
    annotated = [c for c in CASE_IDS if _meta(c).get("extra_sections")]
    assert len(annotated) >= 11
    for case_id in CASE_IDS:
        gold = _gold(case_id)
        facts = [
            *gold.vital_signs,
            *gold.social_history,
            *gold.immunizations,
            *gold.pregnancy,
            *gold.results,
            *gold.procedures,
            *gold.devices,
            *gold.patient.contacts,
        ]
        if case_id in annotated:
            assert gold.vital_signs, case_id
            assert gold.social_history or case_id.startswith(("fi16", "fi14")), case_id
        else:
            assert not facts, case_id


def test_extra_sections_cases_cover_results_procedures_and_devices() -> None:
    annotated = [c for c in CASE_IDS if _meta(c).get("extra_sections")]
    assert all(_gold(c).results for c in annotated if not c.startswith("sv07")), annotated
    assert sum(bool(_gold(c).procedures) for c in annotated) >= 3
    assert sum(bool(_gold(c).devices) for c in annotated) >= 3
    laboratory = {r.category.value for c in annotated for r in _gold(c).results}
    assert laboratory == {"laboratory", "other"}
