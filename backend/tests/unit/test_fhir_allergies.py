"""Allergies mapper: statuses, reactions, empty-section variants and D-7 scoped statements."""

from typing import Any
from uuid import UUID

import pytest

from app.fhir.allergies import SCOPE_CODES, map_allergy, map_allergy_section
from app.fhir.common import MappingContext, NoteCode
from app.fhir.constants import (
    ALLERGY_CLINICAL,
    ALLERGY_VERIFICATION,
    EMPTY_REASON_UNAVAILABLE,
    NO_KNOWN_ALLERGY,
    NO_KNOWN_DRUG_ALLERGY,
    NO_KNOWN_ENVIRONMENTAL_ALLERGY,
    NO_KNOWN_FOOD_ALLERGY,
    SECTION_ALLERGIES,
)
from app.fhir.models import Reference
from app.pipeline.assemble import seeded_id_factory
from app.schemas.intermediate import (
    AllergiesFound,
    AllergyClinicalStatus,
    AllergyCriticality,
    AllergyItem,
    AllergyScope,
    AllergyVerificationStatus,
    Enriched,
    Severity,
)
from tests.assembly_cases import build, nkda_and_items, with_section

PATIENT = Reference(reference="urn:uuid:00000000-0000-4000-8000-000000000001")
CTX = MappingContext(
    patient=PATIENT, new_id=seeded_id_factory(UUID("00000000-0000-4000-8000-0000000000ff"))
)


def _item() -> Enriched[AllergyItem]:
    section = build().allergies
    assert isinstance(section, AllergiesFound)
    return section.items[0]


def _fhir(item: Enriched[AllergyItem]) -> tuple[dict[str, Any], set[NoteCode]]:
    mapped, notes = map_allergy(item, path="allergies.items[0]", patient=PATIENT)
    return mapped.resource.to_fhir(), {n.code for n in notes}


def test_item_mapping_from_fixture() -> None:
    item = _item()
    fhir, notes = _fhir(item)
    assert fhir["id"] == str(item.id)
    assert fhir["code"] == {"text": "Maapähkinä"}  # text only: no lookup coding
    assert fhir["type"] == "allergy"
    assert fhir["category"] == ["food"]
    assert "criticality" not in fhir
    assert "verificationStatus" not in fhir
    assert fhir["onsetDateTime"] == "2015"
    assert fhir["reaction"] == [
        {"manifestation": [{"text": "urtikaria"}, {"text": "huulten turvotus"}]}
    ]
    assert fhir["patient"] == PATIENT.to_fhir()
    assert NoteCode.ALLERGY_CLINICAL_STATUS_DEFAULTED in notes


def test_not_stated_clinical_status_defaults_to_active_with_warning() -> None:
    fhir, notes = _fhir(_item())
    assert fhir["clinicalStatus"]["coding"] == [
        {"system": ALLERGY_CLINICAL, "code": "active", "display": "Active"}
    ]
    assert NoteCode.ALLERGY_CLINICAL_STATUS_DEFAULTED in notes
    assert "assumed" in fhir["text"]["div"]


@pytest.mark.parametrize("status", ["active", "inactive", "resolved"])
def test_clinical_status_mapping(status: str) -> None:
    item = _item()
    item.extracted.clinical_status = AllergyClinicalStatus(status)
    fhir, notes = _fhir(item)
    assert fhir["clinicalStatus"]["coding"][0]["code"] == status
    assert NoteCode.ALLERGY_CLINICAL_STATUS_DEFAULTED not in notes


@pytest.mark.parametrize("status", ["unconfirmed", "confirmed", "refuted"])
def test_verification_status_mapping(status: str) -> None:
    item = _item()
    item.extracted.verification_status = AllergyVerificationStatus(status)
    fhir, _ = _fhir(item)
    assert fhir["verificationStatus"]["coding"] == [
        {"system": ALLERGY_VERIFICATION, "code": status, "display": status.capitalize()}
    ]


def test_criticality_and_reaction_severity() -> None:
    item = _item()
    item.extracted.criticality = AllergyCriticality.UNABLE_TO_ASSESS
    item.extracted.reactions[0].severity = Severity.SEVERE
    fhir, _ = _fhir(item)
    assert fhir["criticality"] == "unable-to-assess"
    assert fhir["reaction"][0]["severity"] == "severe"


def test_reaction_without_manifestation_is_omitted_with_note() -> None:
    item = _item()
    item.extracted.reactions[0].manifestations = []
    fhir, notes = _fhir(item)
    assert "reaction" not in fhir
    assert NoteCode.REACTION_WITHOUT_MANIFESTATION in notes


def test_lookup_codings_are_emitted_printed_code_is_not() -> None:
    data: dict[str, Any] = _item().model_dump(mode="json")
    data["extracted"]["printed_code"] = "T78.1"
    data["codings"] = [
        {
            "path": "substance_text",
            "codings": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "762952008",
                    "display": "Peanut",
                    "lookup": {
                        "server": "https://tx.example.org/r4",
                        "operation": "ValueSet/$expand",
                        "query": "peanut",
                        "selected_by": "deterministic",
                        "retrieved_at": "2026-10-07T09:00:00Z",
                    },
                }
            ],
        }
    ]
    item = Enriched[AllergyItem].model_validate(data)
    fhir, notes = _fhir(item)
    assert fhir["code"] == {
        "coding": [{"system": "http://snomed.info/sct", "code": "762952008", "display": "Peanut"}],
        "text": "Maapähkinä",
    }
    assert "T78.1" not in str(fhir)  # D-9: not a coding, not in the narrative
    assert NoteCode.PRINTED_CODE_NOT_EMITTED in notes


def test_none_known_uses_scope_code() -> None:
    result = map_allergy_section(with_section("allergies", "none_known").allergies, CTX)
    assert len(result.entries) == 1
    fhir = result.entries[0].resource.to_fhir()
    assert fhir["code"]["coding"] == [
        {"system": NO_KNOWN_ALLERGY.system, "code": "716186003", "display": "No known allergy"}
    ]
    assert fhir["clinicalStatus"]["coding"][0]["code"] == "active"
    assert result.entries[0].path == "allergies"
    assert result.section.entry is not None
    assert len(result.section.entry) == 1
    assert result.section.empty_reason is None


def test_scope_codes_cover_every_scope() -> None:
    assert set(SCOPE_CODES) == set(AllergyScope)
    assert SCOPE_CODES[AllergyScope.MEDICATION] == NO_KNOWN_DRUG_ALLERGY


def test_no_information_uses_empty_reason() -> None:
    result = map_allergy_section(with_section("allergies", "no_information").allergies, CTX)
    section = result.section.to_fhir()
    assert result.entries == []
    assert "entry" not in section
    assert section["emptyReason"]["coding"][0]["code"] == EMPTY_REASON_UNAVAILABLE.code
    assert section["code"]["coding"][0]["code"] == SECTION_ALLERGIES.code
    assert "No information available" in section["text"]["div"]


def test_d7_scoped_statements_alongside_items() -> None:
    result = map_allergy_section(nkda_and_items().allergies, CTX)
    by_path = {e.path: e for e in result.entries}
    codes = {
        path: entry.resource.to_fhir()["code"].get("coding", [{}])[0].get("code")
        for path, entry in by_path.items()
    }
    # The food allergy item, NKDA and NK environmental are coded.
    assert codes["allergies.none_known_statements[0]"] == NO_KNOWN_DRUG_ALLERGY.code
    assert codes["allergies.none_known_statements[1]"] == NO_KNOWN_ENVIRONMENTAL_ALLERGY.code
    # "No known food allergy" contradicts the listed peanut (food) allergy; "no allergies" (all)
    # contradicts any listed allergy: both narrative only, with a warning.
    assert "allergies.none_known_statements[2]" not in by_path
    assert "allergies.none_known_statements[3]" not in by_path
    warned = {n.path for n in result.notes if n.code is NoteCode.SCOPED_STATEMENT_NOT_CODED}
    assert warned == {"allergies.none_known_statements[2]", "allergies.none_known_statements[3]"}
    div = result.section.to_fhir()["text"]["div"]
    assert NO_KNOWN_FOOD_ALLERGY.display in div
    assert "not coded" in div
    # Two NKDA statements share one resource.
    nkda = by_path["allergies.none_known_statements[4]"]
    assert nkda.full_url == by_path["allergies.none_known_statements[0]"].full_url
    assert result.section.entry is not None
    refs = [r.reference for r in result.section.entry]
    assert len(refs) == len(set(refs)) == 3


def test_d7_food_statement_is_coded_when_no_food_item() -> None:
    section = nkda_and_items().allergies
    assert isinstance(section, AllergiesFound)
    section.items[0].extracted.category = section.items[0].extracted.category.MEDICATION
    result = map_allergy_section(section, CTX)
    paths = {e.path for e in result.entries}
    assert "allergies.none_known_statements[2]" in paths  # food: now coded
    assert "allergies.none_known_statements[0]" not in paths  # NKDA vs drug allergy: conflict
