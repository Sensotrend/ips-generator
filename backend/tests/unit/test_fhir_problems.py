"""Condition mapper: statuses, partial dates, D-8 past-illness routing, empty-section variants."""

from typing import Any
from uuid import UUID

import pytest

from app.fhir.common import MappingContext, NoteCode
from app.fhir.constants import (
    CONDITION_CLINICAL,
    CONDITION_VER_STATUS,
    NO_CURRENT_PROBLEMS,
    SECTION_PAST_PROBLEMS,
    SECTION_PROBLEMS,
)
from app.fhir.models import Reference
from app.fhir.problems import is_past, map_condition, map_problem_sections
from app.pipeline.assemble import seeded_id_factory
from app.schemas.intermediate import (
    ConditionClinicalStatus,
    ConditionItem,
    ConditionVerificationStatus,
    Enriched,
    ItemsFound,
    Severity,
)
from tests.assembly_cases import build, only_past, past_illness, with_section

PATIENT = Reference(reference="urn:uuid:00000000-0000-4000-8000-000000000001")
CTX = MappingContext(
    patient=PATIENT, new_id=seeded_id_factory(UUID("00000000-0000-4000-8000-0000000000ff"))
)


def _items() -> list[Enriched[ConditionItem]]:
    section = build().problems
    assert isinstance(section, ItemsFound)
    return section.items


def _fhir(item: Enriched[ConditionItem]) -> tuple[dict[str, Any], bool, set[NoteCode]]:
    mapped, past, notes = map_condition(item, path="problems.items[0]", patient=PATIENT)
    return mapped.resource.to_fhir(), past, {n.code for n in notes}


def test_diabetes_from_fixture() -> None:
    fhir, past, notes = _fhir(_items()[0])
    assert not past
    assert fhir["clinicalStatus"]["coding"] == [
        {"system": CONDITION_CLINICAL, "code": "active", "display": "Active"}
    ]
    assert fhir["verificationStatus"]["coding"] == [
        {"system": CONDITION_VER_STATUS, "code": "confirmed", "display": "Confirmed"}
    ]
    assert fhir["code"] == {
        "coding": [
            {
                "system": "http://snomed.info/sct",
                "code": "44054006",
                "display": "Diabetes mellitus type 2",
            }
        ],
        "text": "Tyypin 2 diabetes",
    }
    assert fhir["onsetDateTime"] == "2018"
    assert "E11.9" not in str(fhir)  # D-9
    assert NoteCode.PRINTED_CODE_NOT_EMITTED in notes


def test_not_stated_status_is_assumed_active_on_the_problem_list() -> None:
    fhir, past, notes = _fhir(_items()[1])
    assert not past
    assert fhir["clinicalStatus"]["coding"] == [
        {"system": CONDITION_CLINICAL, "code": "active", "display": "Active"}
    ]
    assert NoteCode.CONDITION_STATUS_ASSUMED_ACTIVE in notes
    assert "assumed" in fhir["text"]["div"]
    assert "verificationStatus" not in fhir
    assert fhir["code"] == {"text": "Verenpainetauti"}


def test_problem_list_entries_have_the_problem_list_item_category() -> None:
    expected = [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                    "code": "problem-list-item",
                    "display": "Problem List Item",
                }
            ]
        }
    ]
    for item in _items():
        fhir, past, _ = _fhir(item)
        assert past or fhir["category"] == expected


def test_past_illness_has_no_category_and_keeps_its_status() -> None:
    item = _items()[1]
    item.extracted.clinical_status = ConditionClinicalStatus.RESOLVED
    fhir, past, notes = _fhir(item)
    assert past
    assert "category" not in fhir
    assert fhir["clinicalStatus"]["coding"][0]["code"] == "resolved"
    assert NoteCode.CONDITION_STATUS_ASSUMED_ACTIVE not in notes


def test_stated_status_gives_no_assumption_note() -> None:
    _, _, notes = _fhir(_items()[0])  # active, stated
    assert NoteCode.CONDITION_STATUS_ASSUMED_ACTIVE not in notes


def test_provisional_with_note() -> None:
    fhir, _, _ = _fhir(_items()[2])
    assert fhir["verificationStatus"]["coding"][0]["code"] == "provisional"
    assert fhir["note"] == [{"text": "tutkimukset kesken"}]


@pytest.mark.parametrize(
    ("status", "past"),
    [
        ("active", False),
        ("recurrence", False),
        ("relapse", False),
        ("not_stated", False),
        ("inactive", True),
        ("remission", True),
        ("resolved", True),
    ],
)
def test_d8_routing_by_status(status: str, past: bool) -> None:
    item = _items()[1]
    item.extracted.clinical_status = ConditionClinicalStatus(status)
    fhir, routed_past, _ = _fhir(item)
    assert routed_past is past
    assert is_past(item.extracted) is past
    expected = "active" if status == "not_stated" else status
    assert fhir["clinicalStatus"]["coding"][0]["code"] == expected


@pytest.mark.parametrize(
    "status", ["unconfirmed", "provisional", "differential", "confirmed", "refuted"]
)
def test_verification_status_mapping(status: str) -> None:
    item = _items()[1]
    item.extracted.verification_status = ConditionVerificationStatus(status)
    fhir, _, _ = _fhir(item)
    assert fhir["verificationStatus"]["coding"][0]["code"] == status


def test_abatement_with_not_stated_status_is_resolved_and_past() -> None:
    item = _items()[1]
    item.extracted.abatement = "2019-11"
    fhir, past, notes = _fhir(item)
    assert past
    assert fhir["clinicalStatus"]["coding"][0]["code"] == "resolved"
    assert fhir["abatementDateTime"] == "2019-11"
    assert NoteCode.CONDITION_STATUS_INFERRED_FROM_ABATEMENT in notes


def test_abatement_conflicting_with_active_is_not_encoded() -> None:
    item = _items()[0]
    item.extracted.abatement = "2020"
    fhir, past, notes = _fhir(item)
    assert not past
    assert "abatementDateTime" not in fhir
    assert NoteCode.ABATEMENT_CONFLICTS_WITH_STATUS in notes
    assert "2020" in fhir["text"]["div"]


def test_severity_and_body_site_text() -> None:
    item = _items()[1]
    item.extracted.severity = Severity.MODERATE
    item.extracted.body_site_text = "vasen polvi"
    fhir, _, _ = _fhir(item)
    assert fhir["severity"] == {"text": "moderate"}
    assert fhir["bodySite"] == [{"text": "vasen polvi"}]


def test_past_illness_section() -> None:
    results = map_problem_sections(past_illness().problems, CTX)
    assert [r.key for r in results] == ["problems", "past_illness"]
    problems, past = results
    assert problems.section.code is not None
    assert past.section.code is not None
    assert problems.section.code.coding is not None
    assert past.section.code.coding is not None
    assert problems.section.code.coding[0].code == SECTION_PROBLEMS.code
    assert past.section.code.coding[0].code == SECTION_PAST_PROBLEMS.code
    assert past.section.title == "History of Past Illness"
    current_paths = {e.path for e in problems.entries}
    past_paths = {e.path for e in past.entries}
    # Fixture items 0-2 (active, not_stated, not_stated) + Migreeni (active; abatement dropped).
    assert current_paths == {f"problems.items[{i}]" for i in (0, 1, 2, 7)}
    # resolved, remission, inactive, not_stated + abatement.
    assert past_paths == {f"problems.items[{i}]" for i in (3, 4, 5, 6)}
    assert past.section.entry is not None
    assert len(past.section.entry) == 4


def test_no_past_section_without_past_conditions() -> None:
    results = map_problem_sections(build().problems, CTX)
    assert [r.key for r in results] == ["problems"]


def test_only_past_conditions_leave_problem_list_empty_with_reason() -> None:
    problems, past = map_problem_sections(only_past().problems, CTX)
    assert problems.entries == []
    assert problems.section.empty_reason is not None
    assert problems.section.entry is None
    assert NoteCode.PROBLEM_LIST_ONLY_PAST in {n.code for n in problems.notes}
    assert len(past.entries) == 1


def test_none_known_section() -> None:
    (result,) = map_problem_sections(with_section("problems", "none_known").problems, CTX)
    fhir = result.entries[0].resource.to_fhir()
    assert fhir["code"]["coding"][0]["code"] == NO_CURRENT_PROBLEMS.code
    assert fhir["clinicalStatus"]["coding"][0]["code"] == "active"


def test_no_information_section() -> None:
    (result,) = map_problem_sections(with_section("problems", "no_information").problems, CTX)
    assert result.entries == []
    assert result.section.empty_reason is not None
