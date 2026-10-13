"""Medication mapper: status mapping, effective[x], dosage, empty-section variants."""

from typing import Any
from uuid import UUID

import pytest

from app.fhir.common import MappingContext, NoteCode
from app.fhir.constants import DATA_ABSENT_REASON_URL, NO_KNOWN_MEDICATIONS
from app.fhir.medications import STATUS, map_medication, map_medication_section
from app.fhir.models import Reference
from app.pipeline.assemble import seeded_id_factory
from app.schemas.intermediate import (
    Enriched,
    ItemsFound,
    MedicationItem,
    MedicationStatus,
    TimeUnit,
)
from tests.assembly_cases import build, with_section

PATIENT = Reference(reference="urn:uuid:00000000-0000-4000-8000-000000000001")
CTX = MappingContext(
    patient=PATIENT, new_id=seeded_id_factory(UUID("00000000-0000-4000-8000-0000000000ff"))
)
DAR = {"extension": [{"url": DATA_ABSENT_REASON_URL, "valueCode": "unknown"}]}


def _items() -> list[Enriched[MedicationItem]]:
    section = build().medications
    assert isinstance(section, ItemsFound)
    return section.items


def _fhir(item: Enriched[MedicationItem]) -> tuple[dict[str, Any], set[NoteCode]]:
    mapped, notes = map_medication(item, path="medications.items[0]", patient=PATIENT)
    return mapped.resource.to_fhir(), {n.code for n in notes}


def test_metformin_full_mapping() -> None:
    fhir, notes = _fhir(_items()[0])
    assert fhir["status"] == "active"
    assert fhir["medicationCodeableConcept"] == {
        "coding": [
            {"system": "http://www.whocc.no/atc", "code": "A10BA02", "display": "metformin"}
        ],
        "text": "Metformin 500 mg tabl",
    }
    assert fhir["dosage"] == [
        {
            "text": "1 x 2 p.o.",
            "timing": {"repeat": {"frequency": 2, "period": 1, "periodUnit": "d"}},
            "route": {"text": "p.o."},
            "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "tabl"}}],
        }
    ]
    assert fhir["_effectiveDateTime"] == DAR
    assert "effectivePeriod" not in fhir
    assert NoteCode.PRINTED_CODE_NOT_EMITTED in notes  # ATC printed in the source (D-9)
    assert NoteCode.MEDICATION_EFFECTIVE_UNKNOWN in notes


def test_prn_without_structured_timing() -> None:
    fhir, notes = _fhir(_items()[2])
    assert fhir["dosage"] == [
        {"text": "1-2 tarvittaessa, enintään 6 vrk:ssa", "asNeededBoolean": True}
    ]
    assert NoteCode.DOSAGE_TIMING_INCOMPLETE not in notes


def test_stopped_with_partial_end_date() -> None:
    fhir, _ = _fhir(_items()[3])
    assert fhir["status"] == "stopped"
    assert fhir["effectivePeriod"] == {"end": "2024-03"}
    assert "_effectiveDateTime" not in fhir
    assert "dosage" not in fhir
    assert fhir["note"] == [{"text": "lopetettu lihaskipujen vuoksi"}]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", "active"),
        ("completed", "completed"),
        ("stopped", "stopped"),
        ("on_hold", "on-hold"),
        ("intended", "intended"),
        ("not_taken", "not-taken"),
        ("not_stated", "unknown"),
    ],
)
def test_status_mapping(status: str, expected: str) -> None:
    item = _items()[0]
    item.extracted.status = MedicationStatus(status)
    fhir, _ = _fhir(item)
    assert fhir["status"] == expected
    assert STATUS[MedicationStatus(status)] == expected


def test_inverted_period_is_not_encoded() -> None:
    item = _items()[0]
    item.extracted.effective_start = "2024-05"
    item.extracted.effective_end = "2023-12"
    fhir, notes = _fhir(item)
    assert "effectivePeriod" not in fhir
    assert fhir["_effectiveDateTime"] == DAR
    assert NoteCode.MEDICATION_PERIOD_INVERTED in notes
    assert "2024-05" in fhir["text"]["div"]


def test_start_only_period() -> None:
    item = _items()[0]
    item.extracted.effective_start = "2018-06-01"
    fhir, _ = _fhir(item)
    assert fhir["effectivePeriod"] == {"start": "2018-06-01"}


def test_incomplete_timing_kept_as_text() -> None:
    item = _items()[0]
    item.extracted.dosage.period_unit = TimeUnit.NOT_STATED
    fhir, notes = _fhir(item)
    assert "timing" not in fhir["dosage"][0]
    assert NoteCode.DOSAGE_TIMING_INCOMPLETE in notes


def test_reason_text() -> None:
    item = _items()[1]
    item.extracted.reason_text = "verenpainetauti"
    fhir, _ = _fhir(item)
    assert fhir["reasonCode"] == [{"text": "verenpainetauti"}]


def test_none_known_section() -> None:
    result = map_medication_section(with_section("medications", "none_known").medications, CTX)
    fhir = result.entries[0].resource.to_fhir()
    assert fhir["medicationCodeableConcept"]["coding"][0]["code"] == NO_KNOWN_MEDICATIONS.code
    assert fhir["_effectiveDateTime"] == DAR
    assert result.section.entry is not None


def test_no_information_section() -> None:
    result = map_medication_section(with_section("medications", "no_information").medications, CTX)
    assert result.entries == []
    assert result.section.empty_reason is not None
    assert result.section.entry is None
