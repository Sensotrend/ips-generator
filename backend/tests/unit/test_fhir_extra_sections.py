"""Optional sections of schema 1.2.0 (PLAN.md D-14): vital signs, social history, immunizations,
pregnancy, patient contacts; the schema, the mappers and their place in the assembled Bundle."""

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.fhir.common import MappingContext, NoteCode
from app.fhir.constants import (
    SECTION_IMMUNIZATIONS,
    SECTION_PREGNANCY,
    SECTION_SOCIAL_HISTORY,
    SECTION_VITAL_SIGNS,
)
from app.fhir.immunizations import map_immunizations, vaccine_code
from app.fhir.models import Reference
from app.fhir.pregnancy import map_pregnancy
from app.fhir.social_history import map_social_history
from app.fhir.vital_signs import map_vital_signs
from app.pipeline.assemble import assemble, seeded_id_factory
from app.pipeline.ground import GroundingStatus, apply_grounding, ground
from app.pipeline.ingest import ingest
from app.review.draft import (
    DraftState,
    ReviewError,
    apply_actions,
    effective_enriched,
    find_fact,
    iter_facts,
    map_back,
    new_draft,
)
from app.review.view import build_draft_view
from app.schemas.api import EditAction, JobStatus, RejectAction
from app.schemas.intermediate import (
    EnrichedIps,
    IpsExtraction,
    extraction_json_schema,
)
from tests.assembly_cases import build

PATIENT = Reference(reference="urn:uuid:00000000-0000-4000-8000-000000000001")
CTX = MappingContext(
    patient=PATIENT, new_id=seeded_id_factory(UUID("00000000-0000-4000-8000-0000000000ff"))
)
NOW = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)


def _prov(quote: str) -> dict[str, Any]:
    return {"source_quote": quote, "page": 1, "locator": "line 1", "confidence": "high"}


def _vital(kind: str, value: str, **extra: str) -> dict[str, Any]:
    base = {"diastolic": "", "unit_text": "", "effective": "2026-10-12", "note": ""}
    return {**_prov(f"{kind} {value}"), "kind": kind, "value": value, **base, **extra}


def _enriched(**sections: list[dict[str, Any]]) -> EnrichedIps:
    base = build()
    data = base.model_dump(mode="json")
    for name, items in sections.items():
        data[name] = [{"extracted": item} for item in items]
    return EnrichedIps.model_validate(data)


def _composition(result: Any) -> dict[str, Any]:
    entries = result.bundle.entry
    assert entries
    resource = entries[0].resource
    assert resource is not None
    fhir: dict[str, Any] = resource.to_fhir()
    return fhir


def _fhir(result: Any) -> list[dict[str, Any]]:
    return [e.resource.to_fhir() for e in result.entries]


# ---- schema -------------------------------------------------------------------------------


def test_schema_version_and_required_properties() -> None:
    schema = extraction_json_schema()
    assert schema["required"] == [
        "document_language",
        "patient",
        "allergies",
        "medications",
        "problems",
        "vital_signs",
        "social_history",
        "immunizations",
        "pregnancy",
    ]
    assert "default" not in str(schema)
    assert "contacts" in schema["$defs"]["PatientExtraction"]["required"]


def test_old_extraction_json_without_the_new_lists_is_still_valid() -> None:
    data = build().model_dump(mode="json")  # EnrichedIps has the lists; strip them to mimic 1.1.x
    extraction = IpsExtraction.model_validate(
        {
            "document_language": "fi",
            "patient": {"names": [], "birth_date": None, "gender": None, "identifiers": []},
            "allergies": {"kind": "no_information"},
            "medications": {"kind": "no_information"},
            "problems": {"kind": "no_information"},
        }
    )
    assert extraction.vital_signs == []
    assert extraction.pregnancy == []
    assert data["vital_signs"] == []


def test_vital_sign_numbers_are_parsed() -> None:
    enriched = _enriched(vital_signs=[_vital("weight", "94,5", unit_text="kg")])
    assert enriched.vital_signs[0].extracted.value == Decimal("94.5")


# ---- vital signs --------------------------------------------------------------------------


def test_vital_signs_become_observations_with_fixed_loinc_and_ucum() -> None:
    enriched = _enriched(
        vital_signs=[
            _vital("height", "1.78", unit_text="m"),
            _vital("weight", "94", unit_text="kg"),
            _vital("blood_pressure", "138", diastolic="84", unit_text="mmHg"),
            _vital("oxygen_saturation", "93", unit_text="%"),
        ]
    )
    result = map_vital_signs(enriched.vital_signs, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_VITAL_SIGNS.code
    height, weight, bp, spo2 = _fhir(result)
    assert height["code"]["coding"][0]["code"] == "8302-2"
    assert height["valueQuantity"] == {
        "value": 178,
        "unit": "cm",
        "system": "http://unitsofmeasure.org",
        "code": "cm",
    }
    assert weight["valueQuantity"]["code"] == "kg"
    assert weight["category"][0]["coding"][0]["code"] == "vital-signs"
    assert weight["effectiveDateTime"] == "2026-10-12"
    assert [c["code"]["coding"][0]["code"] for c in bp["component"]] == ["8480-6", "8462-4"]
    assert bp["code"]["coding"][0]["code"] == "85354-9"
    # The oxygensat profile needs the magic code 2708-6 next to the pulse-oximetry code.
    assert [c["code"] for c in spo2["code"]["coding"]] == ["2708-6", "59408-5"]


def test_unrecognised_unit_is_kept_as_text_not_guessed() -> None:
    enriched = _enriched(vital_signs=[_vital("weight", "190", unit_text="lb")])
    result = map_vital_signs(enriched.vital_signs, CTX)
    assert result is not None
    (obs,) = _fhir(result)
    assert obs["valueString"] == "190 lb"
    assert "valueQuantity" not in obs
    assert NoteCode.VITAL_SIGN_UNIT_UNRECOGNISED in {n.code for n in result.notes}


def test_undated_or_partly_dated_vital_signs_are_narrative_only() -> None:
    enriched = _enriched(
        vital_signs=[
            _vital("height", "168", unit_text="cm", effective=""),
            _vital("weight", "70", unit_text="kg", effective="2026-10"),
            _vital("heart_rate", "84", unit_text="/min"),
        ]
    )
    result = map_vital_signs(enriched.vital_signs, CTX)
    assert result is not None
    assert [e.resource.to_fhir()["code"]["coding"][0]["code"] for e in result.entries] == ["8867-4"]
    assert result.section.text is not None
    div = result.section.text.div
    assert "Body height: 168 cm" in div
    assert "Body weight: 70 kg" in div
    codes = [n.code for n in result.notes]
    assert codes.count(NoteCode.VITAL_SIGN_NOT_DATED) == 2


def test_only_undated_vital_signs_give_a_narrative_only_section() -> None:
    enriched = _enriched(vital_signs=[_vital("height", "168", unit_text="cm", effective="")])
    result = map_vital_signs(enriched.vital_signs, CTX)
    assert result is not None
    assert result.entries == []
    assert result.section.entry is None
    assert result.section.empty_reason is not None
    assert result.section.text is not None
    assert "Body height: 168 cm" in result.section.text.div


def test_empty_optional_sections_are_not_emitted() -> None:
    enriched = _enriched()
    assert map_vital_signs(enriched.vital_signs, CTX) is None
    assert map_social_history(enriched.social_history, CTX) is None
    assert map_immunizations(enriched.immunizations, CTX) is None
    assert map_pregnancy(enriched.pregnancy, CTX) is None


# ---- social history -----------------------------------------------------------------------


def _social(kind: str, use_text: str, status: str = "not_stated", date: str = "") -> dict[str, Any]:
    return {
        **_prov(use_text),
        "kind": kind,
        "tobacco_status": status,
        "use_text": use_text,
        "date": date,
    }


def test_tobacco_is_an_observation_alcohol_stays_in_the_narrative() -> None:
    enriched = _enriched(
        social_history=[
            _social("tobacco", "Tupakointi lopetettu 2019", "former", "2019"),
            _social("tobacco", "Tupakoi toisinaan"),
            _social("alcohol", "Alkoholia ei käytä"),
        ]
    )
    result = map_social_history(enriched.social_history, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_SOCIAL_HISTORY.code
    former, unclear = _fhir(result)  # no alcohol Observation: the IPS profile is a quantity
    assert former["meta"]["profile"][0].endswith("Observation-tobaccouse-uv-ips")
    assert former["code"]["coding"][0]["code"] == "72166-2"
    assert former["valueCodeableConcept"]["coding"][0] == {
        "system": "http://snomed.info/sct",
        "code": "8517006",
        "display": "Ex-smoker",
    }
    assert former["valueCodeableConcept"]["text"] == "Tupakointi lopetettu 2019"
    assert former["effectiveDateTime"] == "2019"
    assert "coding" not in unclear["valueCodeableConcept"]
    assert "effectiveDateTime" not in unclear
    assert unclear["_effectiveDateTime"]["extension"][0]["valueCode"] == "unknown"
    assert result.section.text is not None
    assert "Alcohol use" in result.section.text.div
    assert "Alkoholia ei käytä" in result.section.text.div
    assert [n.code for n in result.notes] == [NoteCode.NOT_REPRESENTABLE_IN_IPS]


def test_only_alcohol_gives_a_narrative_only_section() -> None:
    enriched = _enriched(social_history=[_social("alcohol", "Alkoholia vähän")])
    result = map_social_history(enriched.social_history, CTX)
    assert result is not None
    assert result.entries == []
    assert result.section.entry is None
    assert result.section.empty_reason is not None


# ---- immunizations ------------------------------------------------------------------------


def _vaccine(text: str, occurrence: str = "", status: str = "completed") -> dict[str, Any]:
    return {
        **_prov(text),
        "vaccine_text": text,
        "printed_code": "",
        "printed_code_system_text": "",
        "status": status,
        "occurrence": occurrence,
        "note": "",
    }


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("MPR-rokote", "J07BD52"),
        ("MMR vaccine", "J07BD52"),
        ("vesirokkorokote", "J07BK01"),
        ("influenssarokote", "J07BB"),
        ("koronarokote", "J07BN01"),
        ("jäykkäkouristusrokote", "J07AM01"),
        ("kurkkumätä-jäykkäkouristus-hinkuyskärokote", None),
        ("DTaP-rokote", None),
        ("puutiaisaivokuumerokote", None),
    ],
)
def test_vaccine_table_never_codes_a_combination_as_its_component(
    text: str, code: str | None
) -> None:
    fixed = vaccine_code(text)
    assert (fixed.code if fixed else None) == code


def test_immunizations_map_with_dates_and_text_only_fallbacks() -> None:
    enriched = _enriched(
        immunizations=[
            _vaccine("MPR-rokote", "1996"),
            _vaccine("DTaP-rokote"),
            _vaccine("influenssarokote", "", "not_done"),
        ]
    )
    result = map_immunizations(enriched.immunizations, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_IMMUNIZATIONS.code
    mmr, dtap, flu = _fhir(result)
    assert mmr["vaccineCode"]["coding"][0] == {
        "system": "http://www.whocc.no/atc",
        "code": "J07BD52",
        "display": "measles, combinations with mumps and rubella, live attenuated",
    }
    assert mmr["occurrenceDateTime"] == "1996"
    assert mmr["status"] == "completed"
    assert "coding" not in dtap["vaccineCode"]
    assert dtap["vaccineCode"]["text"] == "DTaP-rokote"
    assert dtap["occurrenceString"] == "Date not stated"
    assert flu["status"] == "not-done"
    assert [n.code for n in result.notes] == [NoteCode.IMMUNIZATION_NOT_CODED]


# ---- pregnancy ----------------------------------------------------------------------------


def _preg(kind: str, **extra: str) -> dict[str, Any]:
    base = {"status": "not_stated", "date": "", "count": "", "note": ""}
    return {**_prov(kind), "kind": kind, **base, **extra}


def test_pregnancy_follows_the_ips_profiles() -> None:
    enriched = _enriched(
        pregnancy=[
            _preg("status", status="pregnant", date="2026-10-12"),
            _preg("expected_delivery_date", date="2027-01-31"),
            _preg("last_menstrual_period", date="2026-04-26"),
            _preg("pregnancies", count="2"),
            _preg("deliveries", count="1"),
        ]
    )
    result = map_pregnancy(enriched.pregnancy, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_PREGNANCY.code
    status, edd, outcome = _fhir(result)  # status first, then the date and the outcome
    assert status["meta"]["profile"][0].endswith("Observation-pregnancy-status-uv-ips")
    assert status["code"]["coding"][0]["code"] == "82810-3"
    assert status["valueCodeableConcept"]["coding"][0]["code"] == "77386006"
    assert status["effectiveDateTime"] == "2026-10-12"
    assert status["hasMember"] == [{"reference": result.entries[1].full_url}]
    assert edd["code"]["coding"][0]["code"] == "11778-8"
    assert edd["valueDateTime"] == "2027-01-31"
    assert edd["_effectiveDateTime"]["extension"][0]["valueCode"] == "unknown"
    assert outcome["code"]["coding"][0]["code"] == "11640-0"
    assert outcome["valueQuantity"] == {
        "value": 1,
        "system": "http://unitsofmeasure.org",
        "code": "1",
    }
    # No IPS element for the number of pregnancies or the last menstrual period: narrative only.
    assert result.section.text is not None
    div = result.section.text.div
    assert "Number of pregnancies: 2" in div
    assert "Last menstrual period: 2026-04-26" in div
    assert [n.code for n in result.notes] == [NoteCode.NOT_REPRESENTABLE_IN_IPS] * 2


def test_pregnancy_fact_without_its_value_is_not_emitted() -> None:
    enriched = _enriched(pregnancy=[_preg("status"), _preg("expected_delivery_date")])
    assert map_pregnancy(enriched.pregnancy, CTX) is None
    # and with one good fact, the bad ones only give a warning each
    enriched = _enriched(pregnancy=[_preg("status"), _preg("deliveries", count="3")])
    result = map_pregnancy(enriched.pregnancy, CTX)
    assert result is not None
    assert len(result.entries) == 1
    assert [n.code for n in result.notes] == [NoteCode.PREGNANCY_FACT_INCOMPLETE]


# ---- assembly, contacts and the review path -----------------------------------------------


def test_assembled_bundle_has_the_sections_in_ips_order_and_the_contact() -> None:
    enriched = _enriched(
        vital_signs=[_vital("height", "168", unit_text="cm")],
        social_history=[_social("tobacco", "Ei tupakoi", "never")],
        immunizations=[_vaccine("MPR-rokote", "1996")],
        pregnancy=[_preg("deliveries", count="2")],
    )
    data = enriched.model_dump(mode="json")
    data["patient"]["contacts"] = [
        {
            **_prov("Teemu Ahonen (puoliso), puh. 040 000 0005"),
            "name_text": "Teemu Ahonen",
            "relationship_text": "puoliso",
            "phone": "040 000 0005",
        }
    ]
    result = assemble(EnrichedIps.model_validate(data), now=NOW)
    composition = _composition(result)
    titles = [s["title"] for s in composition["section"]]
    assert titles == [
        "Problem List",
        "Allergies and Intolerances",
        "Medication Summary",
        "Immunizations",
        "History of Pregnancy",
        "Social History",
        "Vital Signs",
    ]
    sections = {e.section for e in result.entries}
    assert {"immunizations", "pregnancy", "social_history", "vital_signs"} <= sections
    patient = next(
        e.resource.to_fhir()
        for e in result.bundle.entry or []
        if e.resource and e.resource.resource_type == "Patient"
    )
    assert patient["contact"] == [
        {
            "relationship": [{"text": "puoliso"}],
            "name": {"text": "Teemu Ahonen"},
            "telecom": [{"system": "phone", "value": "040 000 0005"}],
        }
    ]


def test_bundle_without_the_new_content_is_unchanged() -> None:
    result = assemble(build(), now=NOW)
    composition = _composition(result)
    assert [s["title"] for s in composition["section"]][:3] == [
        "Problem List",
        "Allergies and Intolerances",
        "Medication Summary",
    ]
    assert not {"immunizations", "pregnancy", "social_history", "vital_signs"} & {
        e.section for e in result.entries
    }


def _draft_with_extras() -> tuple[DraftState, EnrichedIps]:
    enriched = _enriched(
        vital_signs=[
            _vital("height", "168", unit_text="cm"),
            _vital("weight", "70", unit_text="kg"),
        ],
        social_history=[_social("tobacco", "Ei tupakoi", "non_smoker")],
        immunizations=[_vaccine("MPR-rokote", "1996")],
        pregnancy=[_preg("deliveries", count="1")],
    )
    data = enriched.model_dump(mode="json")
    data["patient"]["contacts"] = [
        {
            **_prov("Teemu Ahonen (puoliso), puh. 040 000 0005"),
            "name_text": "Teemu Ahonen",
            "relationship_text": "puoliso",
            "phone": "040 000 0005",
        }
    ]
    full = EnrichedIps.model_validate(data)
    return new_draft(full), full


def test_new_sections_are_reviewable_facts_with_stable_paths() -> None:
    state, _ = _draft_with_extras()
    facts = {f.path: f for f in iter_facts(state.current)}
    assert facts["vital_signs[1]"].kind == "vital_sign"
    assert facts["social_history[0]"].kind == "social_history"
    assert facts["immunizations[0]"].kind == "immunization"
    assert facts["pregnancy[0]"].kind == "pregnancy_fact"
    assert facts["patient.contacts[0]"].kind == "patient_contact"
    assert facts["vital_signs[0]"].section == "vital_signs"
    assert facts["vital_signs[0]"].item_id is not None
    assert facts["patient.contacts[0]"].item_id is None


def test_rejected_facts_leave_the_effective_draft_and_paths_map_back() -> None:
    state, _ = _draft_with_extras()
    state = apply_actions(
        state,
        [
            RejectAction(action="reject", path="vital_signs[0]"),
            RejectAction(action="reject", path="patient.contacts[0]"),
        ],
        actor="t",
        now=NOW,
    )
    effective = effective_enriched(state)
    assert [v.extracted.kind.value for v in effective.enriched.vital_signs] == ["weight"]
    assert effective.enriched.patient.contacts == []
    assert len(effective.enriched.immunizations) == 1
    assert effective.path_map["vital_signs[0]"] == "vital_signs[1]"
    assert map_back("vital_signs[0].something", effective.path_map) == "vital_signs[1].something"
    result = assemble(effective.enriched, now=NOW)
    sections = {e.section for e in result.entries}
    assert {"vital_signs", "immunizations", "pregnancy", "social_history"} <= sections


def test_a_section_with_all_facts_rejected_leaves_the_bundle() -> None:
    state, _ = _draft_with_extras()
    state = apply_actions(
        state, [RejectAction(action="reject", path="immunizations[0]")], actor="t", now=NOW
    )
    result = assemble(effective_enriched(state).enriched, now=NOW)
    assert "immunizations" not in {e.section for e in result.entries}


def test_edit_validates_and_keeps_provenance() -> None:
    state, _ = _draft_with_extras()
    fact = find_fact(state.current, "vital_signs[0]")
    assert fact.value is not None
    value = fact.value.model_dump(mode="json")
    edited = apply_actions(
        state,
        [EditAction(action="edit", path="vital_signs[0]", value={**value, "value": "169"})],
        actor="t",
        now=NOW,
    )
    assert find_fact(edited.current, "vital_signs[0]").value.value == Decimal("169")  # type: ignore[union-attr]
    for bad in (
        {**value, "value": "tall"},
        {**value, "source_quote": "something else"},
        {**value, "kind": "unicorn"},
    ):
        with pytest.raises(ReviewError):
            apply_actions(
                state,
                [EditAction(action="edit", path="vital_signs[0]", value=bad)],
                actor="t",
                now=NOW,
            )


def test_view_lists_the_sections_in_ips_order_with_contacts() -> None:
    state, _ = _draft_with_extras()
    view = build_draft_view(state, job_id=UUID(int=1), version=1, status=JobStatus.REVIEW, now=NOW)
    keys = [s.key for s in view.sections]
    assert keys == [
        "problems",
        "allergies",
        "medications",
        "immunizations",
        "pregnancy",
        "social_history",
        "vital_signs",
    ]
    vitals = next(s for s in view.sections if s.key == "vital_signs")
    assert vitals.kind == "items_found"
    assert vitals.effective_kind == "items_found"
    assert [i.kind for i in vitals.items] == ["vital_sign", "vital_sign"]
    assert vitals.items[0].source is not None
    assert [c.kind for c in view.patient.contacts] == ["patient_contact"]


def test_view_has_no_section_for_what_the_document_did_not_state() -> None:
    state = new_draft(build())
    view = build_draft_view(state, job_id=UUID(int=1), version=1, status=JobStatus.REVIEW, now=NOW)
    assert {s.key for s in view.sections}.isdisjoint(
        {"immunizations", "pregnancy", "social_history", "vital_signs"}
    )
    assert view.patient.contacts == []


def test_non_smoker_has_its_own_value_and_never_means_never() -> None:
    enriched = _enriched(
        social_history=[
            _social("tobacco", "Ei tupakoi", "non_smoker"),
            _social("tobacco", "Ei ole koskaan tupakoinut", "never"),
        ]
    )
    result = map_social_history(enriched.social_history, CTX)
    assert result is not None
    plain, never = _fhir(result)
    assert plain["valueCodeableConcept"]["coding"][0]["code"] == "8392000"
    assert never["valueCodeableConcept"]["coding"][0]["code"] == "266919005"


def test_grounding_covers_the_new_lists_and_drops_unfound_quotes() -> None:
    doc = ingest(b"Pituus 168 cm\nEi tupakoi\nMPR-rokote 1996\n", "text/plain")
    extraction = IpsExtraction.model_validate(
        {
            "document_language": "fi",
            "patient": {"names": [], "birth_date": None, "gender": None, "identifiers": []},
            "allergies": {"kind": "no_information"},
            "medications": {"kind": "no_information"},
            "problems": {"kind": "no_information"},
            "vital_signs": [
                {**_vital("height", "168", unit_text="cm"), "source_quote": "Pituus 168 cm"},
                {**_vital("weight", "70", unit_text="kg"), "source_quote": "paino 70 kg"},
            ],
            "social_history": [
                {
                    **_social("tobacco", "Ei tupakoi"),
                    "source_quote": "Ei tupakoi",
                    "locator": "line 2",
                }
            ],
            "immunizations": [
                {
                    **_vaccine("MPR-rokote", "1996"),
                    "source_quote": "MPR-rokote 1996",
                    "locator": "line 3",
                }
            ],
        }
    )
    report = ground(extraction, doc)
    statuses = {f.path: f.status for f in report.facts}
    assert statuses["vital_signs[0]"] is GroundingStatus.EXACT
    assert statuses["vital_signs[1]"] is GroundingStatus.NOT_FOUND
    assert statuses["social_history[0]"] is GroundingStatus.EXACT
    grounded = apply_grounding(extraction, report)
    assert [v.kind.value for v in grounded.extraction.vital_signs] == ["height"]
    assert grounded.dropped == ("vital_signs[1]",)
    assert len(grounded.extraction.immunizations) == 1
