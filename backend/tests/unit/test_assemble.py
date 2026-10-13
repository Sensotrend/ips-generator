"""assemble(): Bundle structure, determinism, mapping records, review flags."""

import datetime as dt
from uuid import UUID

import pytest

from app.fhir.common import NoteCode
from app.fhir.constants import (
    COMPOSITION_TYPE,
    PROFILE_BUNDLE,
    REQUIRED_SECTIONS,
    SECTION_PAST_PROBLEMS,
    URI_IDENTIFIER_SYSTEM,
)
from app.fhir.device import PipelineInfo
from app.fhir.models import Bundle
from app.pipeline.assemble import assemble, seeded_id_factory
from app.pipeline.derive import apply_derivations
from app.pipeline.ground import ReviewFlag, ReviewReason
from tests.assembly_cases import NOW, all_variants, build, past_illness

ITEM_1 = UUID("0b0c5f3e-6c1a-4b7e-9a51-000000000001")


def test_bundle_shape() -> None:
    result = assemble(build(), now=NOW)
    fhir = result.bundle.to_fhir()
    assert fhir["type"] == "document"
    assert fhir["meta"] == {"profile": [PROFILE_BUNDLE]}
    assert fhir["timestamp"] == "2026-10-08T12:00:00+00:00"
    assert fhir["identifier"] == {
        "system": URI_IDENTIFIER_SYSTEM,
        "value": f"urn:uuid:{fhir['id']}",
    }
    types = [e["resource"]["resourceType"] for e in fhir["entry"]]
    assert types[:3] == ["Composition", "Patient", "Device"]
    assert types.count("Composition") == 1
    for entry in fhir["entry"]:
        assert entry["fullUrl"] == f"urn:uuid:{entry['resource']['id']}"


def test_composition_draft_authored_by_device() -> None:
    fhir = assemble(build(), now=NOW).bundle.to_fhir()
    composition = fhir["entry"][0]["resource"]
    device_url = fhir["entry"][2]["fullUrl"]
    assert composition["status"] == "preliminary"
    assert composition["type"]["coding"] == [
        {
            "system": COMPOSITION_TYPE.system,
            "code": COMPOSITION_TYPE.code,
            "display": COMPOSITION_TYPE.display,
        }
    ]
    assert composition["author"] == [{"reference": device_url}]
    assert "attester" not in composition
    assert composition["subject"] == {"reference": fhir["entry"][1]["fullUrl"]}
    assert composition["date"] == fhir["timestamp"]
    device = fhir["entry"][2]["resource"]
    assert device["deviceName"][0]["name"] == PipelineInfo().name
    assert {v["value"] for v in device["version"]} == {PipelineInfo().version, "1.1.0"}


def test_every_section_has_narrative_and_entries_or_empty_reason() -> None:
    for name, enriched in all_variants().items():
        bundle = assemble(enriched, now=NOW).bundle.to_fhir()
        urls = {e["fullUrl"] for e in bundle["entry"]}
        sections = bundle["entry"][0]["resource"]["section"]
        codes = [s["code"]["coding"][0]["code"] for s in sections]
        assert set(codes[:3]) == {c.code for c in REQUIRED_SECTIONS}, name
        for section in sections:
            assert section["text"]["div"].startswith('<div xmlns="http://www.w3.org/1999/xhtml">')
            assert ("entry" in section) != ("emptyReason" in section), name  # ips-comp-1
            for ref in section.get("entry", []):
                assert ref["reference"] in urls, name


def test_section_order() -> None:
    sections = assemble(past_illness(), now=NOW).bundle.to_fhir()["entry"][0]["resource"]["section"]
    assert [s["code"]["coding"][0]["code"] for s in sections] == [
        "48765-2",
        "10160-0",
        "11450-4",
        SECTION_PAST_PROBLEMS.code,
    ]


def test_deterministic_given_inputs() -> None:
    first = assemble(build(), now=NOW).bundle.to_fhir_json()
    second = assemble(build(), now=NOW).bundle.to_fhir_json()
    assert first == second
    later = assemble(build(), now=NOW + dt.timedelta(hours=1)).bundle.to_fhir_json()
    assert later != first


def test_item_ids_become_full_urls_and_mapping_records() -> None:
    result = assemble(build(), now=NOW)
    assert result.full_url_for(ITEM_1) == f"urn:uuid:{ITEM_1}"
    entry = result.entry_for_path("allergies.items[0]")
    assert entry is not None
    assert (entry.item_id, entry.resource_type, entry.section) == (
        ITEM_1,
        "AllergyIntolerance",
        "allergies",
    )
    statement = result.entry_for_path("allergies.none_known_statements[0]")
    assert statement is not None
    assert statement.item_id is None
    patient = result.entry_for_path("patient")
    assert patient is not None
    assert patient.section is None
    bundle_urls = {e.full_url for e in result.bundle.entry or []}
    assert {e.full_url for e in result.entries} <= bundle_urls


def test_injected_id_factory() -> None:
    seed = UUID("12345678-1234-5678-1234-567812345678")
    result = assemble(build(), now=NOW, new_id=seeded_id_factory(seed))
    patient = result.entry_for_path("patient")
    assert patient is not None
    assert patient.full_url == f"urn:uuid:{seeded_id_factory(seed)('patient')}"


def test_review_flags_are_attached() -> None:
    flags = [
        ReviewFlag(path="allergies.items[0]", reason=ReviewReason.FUZZY_MATCH),
        ReviewFlag(path="patient.names[0]", reason=ReviewReason.RELOCATED),
        ReviewFlag(path="medications.items[1]", reason=ReviewReason.RELOCATED),
    ]
    result = assemble(build(), now=NOW, flags=flags)
    allergy = result.entry_for_path("allergies.items[0]")
    patient = result.entry_for_path("patient")
    med_0 = result.entry_for_path("medications.items[0]")
    med_1 = result.entry_for_path("medications.items[1]")
    assert allergy is not None
    assert allergy.review_flags == (ReviewReason.FUZZY_MATCH,)
    assert patient is not None
    assert patient.review_flags == (ReviewReason.RELOCATED,)
    assert med_0 is not None
    assert med_0.review_flags == ()
    assert med_1 is not None
    assert med_1.review_flags == (ReviewReason.RELOCATED,)


def test_section_unverified_flag_becomes_note() -> None:
    enriched = build(lambda d: d.update({"medications": {"kind": "no_information"}}))
    flags = [ReviewFlag(path="medications", reason=ReviewReason.SECTION_UNVERIFIED)]
    result = assemble(enriched, now=NOW, flags=flags)
    assert any(
        n.code is NoteCode.SECTION_UNVERIFIED and n.path == "medications" for n in result.notes
    )


def test_missing_birth_date_warning_surfaces() -> None:
    result = assemble(build(), now=NOW)
    assert NoteCode.BIRTH_DATE_MISSING in {n.code for n in result.warnings}


def test_bundle_round_trips_through_models() -> None:
    bundle = assemble(build(), now=NOW).bundle
    assert Bundle.model_validate(bundle.to_fhir()).to_fhir() == bundle.to_fhir()


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assemble(build(), now=dt.datetime(2026, 10, 8, 12, 0))


def test_notes_contain_no_document_text() -> None:
    result = assemble(past_illness(), now=NOW)
    for note in result.notes:
        for text in ("Maapähkinä", "Metformin", "Virtanen", "E11.9", "A10BA02", "Migreeni"):
            assert text not in note.message


def test_derived_birth_date_flags_and_notes_on_patient_entry() -> None:
    enriched, flags = apply_derivations(build())
    result = assemble(enriched, now=NOW, flags=flags)
    patient = result.entry_for_path("patient")
    assert patient is not None
    assert patient.review_flags == (ReviewReason.DERIVED_FROM_IDENTITY_CODE,)
    codes = {n.code for n in result.notes}
    assert NoteCode.BIRTH_DATE_DERIVED in codes
    assert NoteCode.BIRTH_DATE_MISSING not in codes
    resource = next(
        e["resource"]
        for e in result.bundle.to_fhir()["entry"]
        if e["resource"]["resourceType"] == "Patient"
    )
    assert resource["birthDate"] == "1972-03-15"
