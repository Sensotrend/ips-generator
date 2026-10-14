"""Optional sections of schema 1.4.0: results, procedures, devices (PLAN.md Phase 2 "Add
sections"); the schema, the mappers, their place in the Bundle and the review layer."""

import datetime as dt
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.fhir.common import MappingContext, NoteCode
from app.fhir.constants import SECTION_MEDICAL_DEVICES, SECTION_PROCEDURES, SECTION_RESULTS
from app.fhir.devices import map_devices
from app.fhir.models import Reference
from app.fhir.procedures import map_procedures
from app.fhir.results import map_results
from app.pipeline.assemble import assemble, seeded_id_factory
from app.pipeline.ground import GroundingStatus, apply_grounding, ground
from app.pipeline.ingest import ingest
from app.review.draft import (
    ReviewError,
    apply_actions,
    effective_enriched,
    find_fact,
    iter_facts,
    new_draft,
)
from app.review.view import build_draft_view
from app.schemas.api import EditAction, JobStatus, RejectAction
from app.schemas.intermediate import EnrichedIps, IpsExtraction, extraction_json_schema
from tests.assembly_cases import build

PATIENT = Reference(reference="urn:uuid:00000000-0000-4000-8000-000000000001")
CTX = MappingContext(
    patient=PATIENT, new_id=seeded_id_factory(UUID("00000000-0000-4000-8000-0000000000ff"))
)
CTX_DATED = MappingContext(patient=PATIENT, new_id=CTX.new_id, document_date="2026-10-12")
NOW = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)


def _prov(quote: str) -> dict[str, Any]:
    return {"source_quote": quote, "page": 1, "locator": "line 1", "confidence": "high"}


def _result(test: str, quote: str = "", **extra: Any) -> dict[str, Any]:
    base = {
        "category": "laboratory",
        "test_text": test,
        "value": "",
        "comparator": "not_stated",
        "value_text": "",
        "unit_text": "",
        "effective": "2026-10-05",
        "note": "",
    }
    return {**_prov(quote or test), **base, **extra}


def _procedure(text: str, **extra: Any) -> dict[str, Any]:
    base = {"procedure_text": text, "body_site_text": "", "performed": "", "note": ""}
    return {**_prov(text), **base, **extra}


def _device(text: str, **extra: Any) -> dict[str, Any]:
    return {**_prov(text), "device_text": text, "brand_text": "", "note": "", **extra}


def _enriched(**sections: list[dict[str, Any]]) -> EnrichedIps:
    data = build().model_dump(mode="json")
    for name, items in sections.items():
        data[name] = [{"extracted": item} for item in items]
    return EnrichedIps.model_validate(data)


def _fhir(result: Any) -> list[dict[str, Any]]:
    return [e.resource.to_fhir() for e in result.entries]


def _titles(result: Any) -> list[str]:
    composition = result.bundle.entry[0].resource.to_fhir()
    return [s["title"] for s in composition["section"]]


# ---- schema --------------------------------------------------------------------------------


def test_new_lists_are_required_in_the_llm_schema_and_have_no_code_fields() -> None:
    schema = extraction_json_schema()
    assert {"results", "procedures", "devices"} <= set(schema["required"])
    assert "default" not in str(schema)
    for name in ("ResultItem", "ProcedureItem", "DeviceItem"):
        props = schema["$defs"][name]["properties"]
        assert next(iter(props)) == "source_quote"
        assert {"page", "locator", "confidence"} <= set(props)
        assert not [p for p in props if "code" in p or p == "printed_code"]


def test_result_numbers_comparators_and_bad_values() -> None:
    item = _enriched(results=[_result("HbA1c", value="5,2", comparator="GT")]).results[0]
    assert str(item.extracted.value) == "5.2"
    assert item.extracted.comparator.value == "gt"
    for bad in ({"value": "-2,7"}, {"effective": "5.10.2026"}, {"category": "imaging"}):
        with pytest.raises(ValidationError):
            _enriched(results=[_result("x", **bad)])


# ---- results -------------------------------------------------------------------------------


def test_laboratory_results_become_observations_with_the_text_as_code() -> None:
    enriched = _enriched(
        results=[
            _result("Hb", "Hb 112 g/l", value="112", unit_text="g/l"),
            _result("eGFR", value="90", comparator="gt", unit_text="ml/min", effective=""),
            _result("rubella IgG", "rubella IgG positive", value_text="positive"),
        ]
    )
    result = map_results(enriched.results, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_RESULTS.code
    hb, egfr, rubella = _fhir(result)
    assert hb["code"] == {"text": "Hb"}  # no code without a terminology lookup (D-1)
    assert hb["category"][0]["coding"][0]["code"] == "laboratory"
    assert hb["valueQuantity"] == {"value": 112, "unit": "g/l"}
    assert hb["effectiveDateTime"] == "2026-10-05"
    assert egfr["valueQuantity"]["comparator"] == ">"
    assert rubella["valueString"] == "positive"
    # The IPS laboratory profile needs a performer: the documents never give one.
    assert hb["performer"][0]["extension"][0]["valueCode"] == "unknown"
    assert "reference" not in hb["performer"][0]


def test_undated_results_take_the_document_date_as_a_stand_in() -> None:
    enriched = _enriched(results=[_result("Hb", value="112", effective="")])
    dated = map_results(enriched.results, CTX_DATED)
    assert dated is not None
    (obs,) = _fhir(dated)
    assert obs["effectiveDateTime"] == "2026-10-12"
    assert NoteCode.EFFECTIVE_IS_DOCUMENT_DATE in {n.code for n in dated.notes}
    undated = map_results(enriched.results, CTX)
    assert undated is not None
    (obs,) = _fhir(undated)
    assert "effectiveDateTime" not in obs
    assert obs["_effectiveDateTime"]["extension"][0]["valueCode"] == "unknown"


def test_a_result_without_any_value_has_a_data_absent_reason() -> None:
    enriched = _enriched(results=[_result("CRP")])
    result = map_results(enriched.results, CTX)
    assert result is not None
    (obs,) = _fhir(result)
    assert obs["dataAbsentReason"]["coding"][0]["code"] == "unknown"
    assert NoteCode.RESULT_WITHOUT_VALUE in {n.code for n in result.notes}


def test_non_laboratory_tests_stay_in_the_narrative_only() -> None:
    enriched = _enriched(
        results=[_result("Spirometria, FEV1", category="other", value="62", unit_text="% ref")]
    )
    result = map_results(enriched.results, CTX)
    assert result is not None
    assert result.entries == []
    assert result.section.empty_reason is not None  # ips-comp-1: no entries, emptyReason
    assert result.section.text is not None
    assert "Spirometria, FEV1" in result.section.text.div
    assert NoteCode.NOT_REPRESENTABLE_IN_IPS in {n.code for n in result.notes}


# ---- procedures ----------------------------------------------------------------------------


def test_procedures_map_with_a_date_or_the_date_not_stated_string() -> None:
    enriched = _enriched(
        procedures=[
            _procedure("appendektomi", performed="2008"),
            _procedure("Koloskopi", body_site_text="paksusuoli", note="seuranta"),
        ]
    )
    result = map_procedures(enriched.procedures, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_PROCEDURES.code
    appendectomy, colonoscopy = _fhir(result)
    assert appendectomy["status"] == "completed"
    assert appendectomy["code"] == {"text": "appendektomi"}
    assert appendectomy["performedDateTime"] == "2008"
    assert colonoscopy["performedString"] == "Date not stated"
    assert colonoscopy["bodySite"] == [{"text": "paksusuoli"}]
    assert colonoscopy["note"] == [{"text": "seuranta"}]
    assert [n.code for n in result.notes] == [NoteCode.PROCEDURE_NOT_DATED]


# ---- devices -------------------------------------------------------------------------------


def test_a_device_is_a_use_statement_pointing_at_a_device() -> None:
    enriched = _enriched(
        devices=[
            _device("Inhalaatiovälikammio", brand_text="Volumatic"),
            _device("kävelykeppi"),
        ]
    )
    result = map_devices(enriched.devices, CTX)
    assert result is not None
    assert result.section.code is not None
    assert result.section.code.coding is not None
    assert result.section.code.coding[0].code == SECTION_MEDICAL_DEVICES.code
    assert len(result.entries) == 4  # a statement and a Device per item
    resources = _fhir(result)
    statements = [r for r in resources if r["resourceType"] == "DeviceUseStatement"]
    devices = {r["id"]: r for r in resources if r["resourceType"] == "Device"}
    assert len(statements) == 2
    assert statements[0]["status"] == "active"
    assert statements[0]["_timingDateTime"]["extension"][0]["valueCode"] == "unknown"
    spacer = next(d for d in devices.values() if d["type"] == {"text": "Inhalaatiovälikammio"})
    assert spacer["deviceName"] == [{"name": "Volumatic", "type": "user-friendly-name"}]
    assert statements[0]["device"]["reference"] == f"urn:uuid:{spacer['id']}"
    # Only the statements are section entries.
    assert [e["reference"] for e in result.section.to_fhir()["entry"]] == [
        f"urn:uuid:{s['id']}" for s in statements
    ]


def test_device_ids_are_stable_across_assemblies() -> None:
    enriched = _enriched(devices=[_device("kävelykeppi")])
    first = map_devices(enriched.devices, CTX)
    second = map_devices(enriched.devices, CTX)
    assert first is not None
    assert second is not None
    assert [e.full_url for e in first.entries] == [e.full_url for e in second.entries]


# ---- assembly and review -------------------------------------------------------------------


def _full() -> EnrichedIps:
    return _enriched(
        results=[_result("Hb", value="112", unit_text="g/l"), _result("CRP", value="3")],
        procedures=[_procedure("appendektomi", performed="2008")],
        devices=[_device("kävelykeppi")],
    )


def test_assembled_bundle_has_the_new_sections_in_ips_order() -> None:
    result = assemble(_full(), now=NOW)
    assert _titles(result) == [
        "Problem List",
        "Allergies and Intolerances",
        "Medication Summary",
        "Results",
        "History of Procedures",
        "Medical Devices",
    ]
    assert {"results", "procedures", "devices"} <= {e.section for e in result.entries}
    types = [e.resource_type for e in result.entries if e.section == "devices"]
    assert types == ["DeviceUseStatement", "Device"]


def test_bundle_without_the_new_content_has_no_such_section() -> None:
    result = assemble(build(), now=NOW)
    assert not {"results", "procedures", "devices"} & {e.section for e in result.entries}


def test_new_sections_are_reviewable_facts_and_rejection_removes_them() -> None:
    state = new_draft(_full())
    facts = {f.path: f for f in iter_facts(state.current)}
    assert facts["results[1]"].kind == "result"
    assert facts["procedures[0]"].kind == "procedure"
    assert facts["devices[0]"].kind == "device"
    assert facts["results[0]"].section == "results"
    state = apply_actions(
        state,
        [
            RejectAction(action="reject", path="results[0]"),
            RejectAction(action="reject", path="devices[0]"),
        ],
        actor="t",
        now=NOW,
    )
    effective = effective_enriched(state)
    assert [r.extracted.test_text for r in effective.enriched.results] == ["CRP"]
    assert effective.path_map["results[0]"] == "results[1]"
    assert effective.enriched.devices == []
    assembled = assemble(effective.enriched, now=NOW)
    assert "devices" not in {e.section for e in assembled.entries}
    assert "results" in {e.section for e in assembled.entries}


def test_edit_a_result_keeps_its_provenance_and_validates() -> None:
    state = new_draft(_full())
    fact = find_fact(state.current, "results[0]")
    assert fact.value is not None
    value = fact.value.model_dump(mode="json")
    edited = apply_actions(
        state,
        [EditAction(action="edit", path="results[0]", value={**value, "value": "118"})],
        actor="t",
        now=NOW,
    )
    assert str(edited.current.results[0].extracted.value) == "118"
    for bad in (
        {**value, "value": "high"},
        {**value, "source_quote": "something else"},
        {**value, "category": "imaging"},
    ):
        with pytest.raises(ReviewError):
            apply_actions(
                state,
                [EditAction(action="edit", path="results[0]", value=bad)],
                actor="t",
                now=NOW,
            )


def test_view_lists_the_new_sections_after_the_required_ones() -> None:
    view = build_draft_view(
        new_draft(_full()), job_id=UUID(int=1), version=1, status=JobStatus.REVIEW, now=NOW
    )
    assert [s.key for s in view.sections] == [
        "problems",
        "allergies",
        "medications",
        "results",
        "procedures",
        "devices",
    ]
    results = next(s for s in view.sections if s.key == "results")
    assert [i.kind for i in results.items] == ["result", "result"]
    assert results.items[0].source is not None


# ---- grounding -----------------------------------------------------------------------------


def test_grounding_covers_the_new_lists_and_drops_unfound_quotes() -> None:
    doc = ingest("Hb 112 g/l\nappendektomi 2008\nkävelykeppi\n".encode(), "text/plain")
    extraction = IpsExtraction.model_validate(
        {
            "document_language": "fi",
            "patient": {"names": [], "birth_date": None, "gender": None, "identifiers": []},
            "allergies": {"kind": "no_information"},
            "medications": {"kind": "no_information"},
            "problems": {"kind": "no_information"},
            "results": [
                _result("Hb", "Hb 112 g/l", value="112"),
                _result("CRP", "CRP 3 mg/l", value="3"),
            ],
            "procedures": [
                {
                    **_procedure("appendektomi"),
                    "source_quote": "appendektomi 2008",
                    "locator": "line 2",
                }
            ],
            "devices": [{**_device("kävelykeppi"), "locator": "line 3"}],
        }
    )
    report = ground(extraction, doc)
    statuses = {f.path: f.status for f in report.facts}
    assert statuses["results[0]"] is GroundingStatus.EXACT
    assert statuses["results[1]"] is GroundingStatus.NOT_FOUND
    assert statuses["procedures[0]"] is GroundingStatus.EXACT
    grounded = apply_grounding(extraction, report)
    assert [r.test_text for r in grounded.extraction.results] == ["Hb"]
    assert grounded.dropped == ("results[1]",)
    assert len(grounded.extraction.procedures) == 1
    assert len(grounded.extraction.devices) == 1
