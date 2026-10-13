"""Tests for the intermediate schema (app/schemas/intermediate.py)."""

import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import anthropic
import pytest
from pydantic import ValidationError

from app.schemas.intermediate import (
    AllergiesFound,
    AllergyCategory,
    AllergyItem,
    ConditionItem,
    Confidence,
    Enriched,
    EnrichedIps,
    IpsExtraction,
    ItemsFound,
    MedicationItem,
    NoInformation,
    NoKnownAllergies,
    NoKnownAllergyStatement,
    NoneKnown,
    Severity,
    TimeUnit,
    extraction_json_schema,
    extraction_output_format,
    path_pattern,
    resolve_path,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "intermediate"
SOURCE_TEXT = (FIXTURES / "discharge_summary_fi.txt").read_text(encoding="utf-8")
EXTRACTION_JSON = (FIXTURES / "extraction_discharge_summary_fi.json").read_text(encoding="utf-8")
ENRICHED_JSON = (FIXTURES / "enriched_discharge_summary_fi.json").read_text(encoding="utf-8")


def _raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXTRACTION_JSON)
    return data


def _first_allergy(data: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = data["allergies"]["items"][0]
    return item


def _grounded_facts(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if "source_quote" in node:
            yield node
        for value in node.values():
            yield from _grounded_facts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _grounded_facts(value)


# --- LLM extraction layer -------------------------------------------------------------------


def test_extraction_fixture_validates() -> None:
    extraction = IpsExtraction.model_validate_json(EXTRACTION_JSON)

    assert extraction.document_language == "fi"
    assert extraction.patient.birth_date is None  # not stated; never derived from the HETU
    assert isinstance(extraction.allergies, AllergiesFound)
    allergy = extraction.allergies.items[0]
    assert isinstance(allergy, AllergyItem)
    assert allergy.category is AllergyCategory.FOOD
    assert allergy.note is None  # "" in LLM JSON -> None
    assert allergy.printed_code is None
    [nkda] = extraction.allergies.none_known_statements  # D-7: NKDA next to a food allergy
    assert isinstance(nkda, NoKnownAllergyStatement)
    assert nkda.scope == "medication"
    assert isinstance(extraction.medications, ItemsFound)
    metformin = extraction.medications.items[0]
    assert metformin.medication_text == "Metformin"  # D-9: the code is not in the text field
    assert (metformin.printed_code, metformin.printed_code_system_text) == ("A10BA02", "ATC")
    assert isinstance(extraction.problems, ItemsFound)
    diabetes = extraction.problems.items[0]
    assert (diabetes.printed_code, diabetes.printed_code_system_text) == ("E11.9", None)
    assert metformin.dosage.dose_value == Decimal("1")
    assert metformin.dosage.frequency == 2
    assert metformin.dosage.period_unit is TimeUnit.D
    panadol = extraction.medications.items[2]
    assert panadol.dosage.as_needed
    assert panadol.dosage.dose_value is None  # a range stays text only
    assert extraction.medications.items[3].effective_end == "2024-03"


def test_extraction_fixture_quotes_are_grounded_in_source() -> None:
    """Every quote is a verbatim substring of the segment its page/locator points to."""
    lines = SOURCE_TEXT.splitlines()
    facts = list(_grounded_facts(_raw()))
    assert len(facts) == 12
    for fact in facts:
        assert fact["page"] == 1  # plaintext is non-paged
        line_no = int(fact["locator"].removeprefix("line "))
        assert fact["source_quote"] in lines[line_no - 1]


def test_extraction_round_trips_through_python_json() -> None:
    extraction = IpsExtraction.model_validate_json(EXTRACTION_JSON)
    again = IpsExtraction.model_validate_json(extraction.model_dump_json())
    assert again == extraction


def test_enum_values_are_case_insensitive() -> None:
    data = _raw()
    allergy = _first_allergy(data)
    allergy["confidence"] = "HIGH"
    allergy["criticality"] = "Not stated"
    allergy["reactions"][0]["severity"] = "Not-Stated"
    data["problems"] = {"kind": "No_Information"}

    extraction = IpsExtraction.model_validate(data)

    assert isinstance(extraction.allergies, ItemsFound)
    assert extraction.allergies.items[0].confidence is Confidence.HIGH
    assert extraction.allergies.items[0].reactions[0].severity is Severity.NOT_STATED
    assert isinstance(extraction.problems, NoInformation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_quote", "   "),
        ("page", 0),
        ("onset", "2024-13"),
        ("onset", "2023-02-30"),
        ("onset", "15.3.1972"),
        ("category", "drug"),
        ("unexpected", "x"),
    ],
)
def test_invalid_item_values_are_rejected(field: str, value: object) -> None:
    data = _raw()
    _first_allergy(data)[field] = value
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)


@pytest.mark.parametrize("onset", ["2015", "2015-06", "2015-06-30", ""])
def test_partial_dates(onset: str) -> None:
    data = _raw()
    _first_allergy(data)["onset"] = onset
    extraction = IpsExtraction.model_validate(data)
    assert isinstance(extraction.allergies, ItemsFound)
    assert extraction.allergies.items[0].onset == (onset or None)


def test_dosage_numbers() -> None:
    data = _raw()
    dosage = data["medications"]["items"][0]["dosage"]
    dosage["dose_value"] = "0,5"
    extraction = IpsExtraction.model_validate(data)
    assert isinstance(extraction.medications, ItemsFound)
    assert extraction.medications.items[0].dosage.dose_value == Decimal("0.5")

    dosage["dose_value"] = "1-2"
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)
    dosage["dose_value"] = "1"
    dosage["frequency"] = "2.5"
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)


# --- Required-section semantics (D7) --------------------------------------------------------

NONE_KNOWN = {
    "kind": "none_known",
    "source_quote": "Ei säännöllistä lääkitystä",
    "page": 1,
    "locator": "line 3",
    "confidence": "high",
}


def test_section_variants() -> None:
    data = _raw()
    data["allergies"] = {**NONE_KNOWN, "source_quote": "NKDA", "scope": "medication"}
    data["medications"] = NONE_KNOWN
    data["problems"] = {"kind": "no_information"}

    extraction = IpsExtraction.model_validate(data)

    assert isinstance(extraction.allergies, NoKnownAllergies)
    assert extraction.allergies.scope == "medication"
    assert isinstance(extraction.medications, NoneKnown)
    assert isinstance(extraction.problems, NoInformation)


@pytest.mark.parametrize(
    "section",
    [
        {"kind": "items_found", "items": []},  # empty list is never a valid answer
        {"kind": "none_known"},  # "none known" needs its own evidence
        {**NONE_KNOWN, "source_quote": ""},
        {"kind": "no_information", "items": []},
        {"items": []},  # no tag
        [],
    ],
)
def test_ambiguous_sections_are_rejected(section: object) -> None:
    data = _raw()
    data["medications"] = section
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)


@pytest.mark.parametrize(
    ("section", "loc", "error_type"),
    [
        ({"kind": "none_kn0wn"}, ("medications",), "invalid_section_kind"),
        ({"items": []}, ("medications",), "invalid_section_kind"),
        ([], ("medications",), "invalid_section_kind"),
        ({"kind": "none_known"}, ("medications", "none_known", "source_quote"), "missing"),
        (
            {"kind": "items_found", "items": []},
            ("medications", "items_found", "items"),
            "too_short",
        ),
    ],
)
def test_section_errors_are_per_variant(
    section: object, loc: tuple[str, ...], error_type: str
) -> None:
    """Discriminated unions: errors name the chosen variant only, never other branches, and an
    unknown ``kind`` gets a fixed message without the input value."""
    data = _raw()
    data["medications"] = section
    with pytest.raises(ValidationError) as info:
        IpsExtraction.model_validate(data)
    errors = info.value.errors(include_url=False)
    assert errors[0]["loc"] == loc
    assert errors[0]["type"] == error_type
    assert all(e["loc"][:1] == ("medications",) for e in errors)
    assert not any(e["loc"][1:2] == ("no_information",) for e in errors)
    if error_type == "invalid_section_kind":
        assert len(errors) == 1
        assert "none_kn0wn" not in errors[0]["msg"]


def test_allergies_items_found_requires_statement_list() -> None:
    data = _raw()
    del data["allergies"]["none_known_statements"]
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)
    data["allergies"]["none_known_statements"] = []
    assert isinstance(IpsExtraction.model_validate(data).allergies, AllergiesFound)


def test_medications_items_found_has_no_statement_list() -> None:
    """IPS has no scoped "no known ..." for medications or problems."""
    data = _raw()
    data["medications"]["none_known_statements"] = []
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)


def test_allergy_none_known_requires_scope() -> None:
    data = _raw()
    data["allergies"] = NONE_KNOWN
    with pytest.raises(ValidationError):
        IpsExtraction.model_validate(data)


# --- JSON schema: Claude structured-outputs constraints ------------------------------------

ALLOWED_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "description",
    "enum",
    "const",
    "anyOf",
    "items",
    "minItems",
    "pattern",
    "$ref",
    "$defs",
}


def _schemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every (sub)schema, including $defs entries."""
    yield schema
    for sub in schema.get("properties", {}).values():
        yield from _schemas(sub)
    for sub in schema.get("$defs", {}).values():
        yield from _schemas(sub)
    for sub in schema.get("anyOf", []):
        yield from _schemas(sub)
    if isinstance(schema.get("items"), dict):
        yield from _schemas(schema["items"])


def _refs(schema: Any) -> set[str]:
    if isinstance(schema, dict):
        found = {schema["$ref"].removeprefix("#/$defs/")} if "$ref" in schema else set()
        for value in schema.values():
            found |= _refs(value)
        return found
    if isinstance(schema, list):
        return set().union(*(_refs(v) for v in schema)) if schema else set()
    return set()


def test_schema_uses_only_supported_keywords() -> None:
    schema = extraction_json_schema()
    for sub in _schemas(schema):
        assert set(sub) <= ALLOWED_KEYWORDS, set(sub) - ALLOWED_KEYWORDS
        if "$ref" in sub:
            assert set(sub) == {"$ref"}, "no sibling keywords next to $ref"
        if "minItems" in sub:
            assert sub["minItems"] in {0, 1}
        if "enum" in sub:
            assert all(isinstance(v, str) and v == v.lower() for v in sub["enum"])
        if "pattern" in sub:
            assert not re.search(r"\(\?[=!<]|\\[1-9]|\\[bB]", sub["pattern"])


def test_schema_objects_are_closed_and_fully_required() -> None:
    """Optional properties are capped at 24 per request; we use none."""
    for sub in _schemas(extraction_json_schema()):
        if sub.get("type") == "object":
            assert sub["additionalProperties"] is False
            assert sub["required"] == list(sub["properties"])


def test_schema_union_budget() -> None:
    """Union-typed properties are capped at 16 per request: 3 sections + birth_date + gender
    (the discriminated sections are emitted as ``anyOf``, never ``oneOf``)."""
    unions = [
        name
        for sub in _schemas(extraction_json_schema())
        for name, prop in sub.get("properties", {}).items()
        if "anyOf" in prop
    ]
    assert sorted(unions) == ["allergies", "birth_date", "gender", "medications", "problems"]


def test_schema_is_not_recursive() -> None:
    schema = extraction_json_schema()
    defs = schema["$defs"]
    graph = {name: _refs(d) for name, d in defs.items()}
    assert set().union(*graph.values()) <= set(defs)

    def visit(name: str, stack: tuple[str, ...]) -> None:
        assert name not in stack, f"recursive $ref: {(*stack, name)}"
        for child in graph[name]:
            visit(child, (*stack, name))

    for name in _refs({k: v for k, v in schema.items() if k != "$defs"}):
        visit(name, ())


PRINTED_CODE_FIELDS = {"printed_code", "printed_code_system_text"}


def test_schema_has_no_code_fields() -> None:
    """D2/D-1: the LLM never emits codes or code systems, except D-9 printed-code hints."""
    names = {
        name for sub in _schemas(extraction_json_schema()) for name in sub.get("properties", {})
    }
    assert {n for n in names if re.search(r"code|coding|system|uri", n)} == PRINTED_CODE_FIELDS


def test_printed_code_fields_follow_the_term() -> None:
    defs = extraction_json_schema()["$defs"]
    for name, term in (
        ("AllergyItem", "substance_text"),
        ("MedicationItem", "medication_text"),
        ("ConditionItem", "condition_text"),
    ):
        props = list(defs[name]["properties"])
        at = props.index(term)
        assert props[at + 1 : at + 3] == ["printed_code", "printed_code_system_text"], name
        description = defs[name]["properties"]["printed_code"]["description"]
        assert "source_quote" in description
        assert "Never supply a code yourself" in description
    assert PRINTED_CODE_FIELDS.isdisjoint(
        set().union(*(m.codable_paths for m in (AllergyItem, MedicationItem, ConditionItem)))
    )


def test_every_fact_schema_has_provenance() -> None:
    defs = extraction_json_schema()["$defs"]
    grounded = {
        "AllergyItem",
        "MedicationItem",
        "ConditionItem",
        "PatientName",
        "PatientIdentifier",
        "BirthDate",
        "Gender",
        "NoneKnown",
        "NoKnownAllergies",
        "NoKnownAllergyStatement",
    }
    for name in grounded:
        props = defs[name]["properties"]
        assert {"source_quote", "page", "locator", "confidence"} <= set(props), name
        assert next(p for p in props if p != "kind") == "source_quote", "quote comes first"


def test_output_format_and_sdk_transform() -> None:
    output_format = extraction_output_format()
    assert output_format["type"] == "json_schema"
    assert output_format["schema"]["type"] == "object"
    # messages.parse(output_format=IpsExtraction) must also be able to build a schema.
    assert anthropic.transform_schema(IpsExtraction)["type"] == "object"


# --- Enriched layer -------------------------------------------------------------------------


def test_enriched_fixture_validates() -> None:
    enriched = EnrichedIps.model_validate_json(ENRICHED_JSON)

    assert isinstance(enriched.problems, ItemsFound)
    diabetes = enriched.problems.items[0]
    assert isinstance(diabetes.extracted, ConditionItem)
    [coding] = diabetes.codings_for("condition_text")
    assert (coding.system, coding.code) == ("http://snomed.info/sct", "44054006")
    assert coding.lookup.model == "claude-sonnet-5-5"
    assert diabetes.codings_for("body_site_text") == []
    assert isinstance(enriched.medications, ItemsFound)
    assert isinstance(enriched.medications.items[0].extracted, MedicationItem)
    assert EnrichedIps.model_validate_json(enriched.model_dump_json()) == enriched


def test_from_extraction_carries_none_known_statements_and_printed_codes() -> None:
    extraction = IpsExtraction.model_validate_json(EXTRACTION_JSON)

    enriched = EnrichedIps.from_extraction(extraction)

    assert isinstance(extraction.allergies, AllergiesFound)
    assert isinstance(enriched.allergies, AllergiesFound)
    assert enriched.allergies.none_known_statements == extraction.allergies.none_known_statements
    assert enriched.allergies.none_known_statements[0].scope == "medication"
    assert isinstance(enriched.medications, ItemsFound)
    metformin = enriched.medications.items[0]
    assert metformin.extracted.printed_code == "A10BA02"
    assert metformin.codings_for("printed_code") == []  # a hint, never a coding
    again = EnrichedIps.model_validate_json(enriched.model_dump_json())
    assert again == enriched


def test_enriched_rejects_coding_of_printed_code() -> None:
    """D-9: a printed code is a hint; codings come only from terminology lookups of text."""
    condition = ConditionItem.model_validate(json.loads(EXTRACTION_JSON)["problems"]["items"][0])
    assert condition.printed_code == "E11.9"
    with pytest.raises(ValidationError, match="not codable"):
        Enriched[ConditionItem].model_validate(
            {"extracted": condition, "codings": [{"path": "printed_code", "codings": [_coding()]}]}
        )


def test_from_extraction_wraps_items_and_keeps_other_variants() -> None:
    data = _raw()
    data["medications"] = NONE_KNOWN
    data["problems"] = {"kind": "no_information"}
    extraction = IpsExtraction.model_validate(data)

    enriched = EnrichedIps.from_extraction(extraction)

    assert isinstance(enriched.allergies, AllergiesFound)
    [wrapped] = enriched.allergies.items
    assert isinstance(extraction.allergies, ItemsFound)
    assert wrapped.extracted == extraction.allergies.items[0]
    assert wrapped.codings == []
    assert enriched.medications == extraction.medications
    assert isinstance(enriched.problems, NoInformation)


def _coding(**lookup_overrides: object) -> dict[str, object]:
    lookup: dict[str, object] = {
        "server": "https://tx.example.org/fhir",
        "operation": "ValueSet/$expand",
        "query": "urticaria",
        "selected_by": "deterministic",
        "retrieved_at": "2026-10-07T09:00:00Z",
        **lookup_overrides,
    }
    return {"system": "http://snomed.info/sct", "code": "123", "display": "x", "lookup": lookup}


def _allergy() -> AllergyItem:
    return AllergyItem.model_validate(_first_allergy(_raw()))


def test_codable_paths_resolve() -> None:
    allergy = _allergy()
    assert resolve_path(allergy, "reactions[0].manifestations[1]") == "huulten turvotus"
    assert path_pattern("reactions[0].manifestations[1]") == "reactions[*].manifestations[*]"
    for model in (AllergyItem, MedicationItem, ConditionItem):
        assert model.codable_paths


@pytest.mark.parametrize(
    ("path", "coding"),
    [
        ("reactions[0].manifestations[0]", _coding()),
        ("substance_text", _coding(selected_by="tool_loop", model="claude-sonnet-5-5")),
    ],
)
def test_enriched_accepts_valid_codings(path: str, coding: dict[str, object]) -> None:
    item = Enriched[AllergyItem].model_validate(
        {"extracted": _allergy(), "codings": [{"path": path, "codings": [coding]}]}
    )
    assert item.codings_for(path)[0].code == "123"


@pytest.mark.parametrize(
    ("path", "coding"),
    [
        ("note", _coding()),  # not a codable field
        ("reactions[3].manifestations[0]", _coding()),  # out of range
        ("substance_text", _coding(selected_by="tool_loop")),  # tool loop must name the model
        ("substance_text", {**_coding(), "system": "SNOMED CT"}),  # not a canonical URI
        ("substance_text", {**_coding(), "code": ""}),
    ],
)
def test_enriched_rejects_invalid_codings(path: str, coding: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Enriched[AllergyItem].model_validate(
            {"extracted": _allergy(), "codings": [{"path": path, "codings": [coding]}]}
        )


def test_enriched_rejects_coding_of_unstated_value() -> None:
    condition = ConditionItem.model_validate(json.loads(EXTRACTION_JSON)["problems"]["items"][1])
    for path in ("body_site_text", "severity"):  # "" -> None and not_stated
        with pytest.raises(ValidationError):
            Enriched[ConditionItem].model_validate(
                {"extracted": condition, "codings": [{"path": path, "codings": [_coding()]}]}
            )
