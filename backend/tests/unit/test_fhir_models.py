"""Tests for the thin FHIR R4 models (D-6): IG example round-trips and strictness."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.fhir.models import (
    MODELLED_RESOURCES,
    AllergyIntolerance,
    Bundle,
    CodeableConcept,
    Coding,
    Composition,
    Condition,
    Extension,
    GenericResource,
    MedicationStatement,
    Patient,
    PrimitiveElement,
    Quantity,
    Reference,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
BUNDLE_FILES = sorted((FIXTURES / "ips-examples").glob("*.json")) + sorted(
    (FIXTURES / "ips-variants").glob("*.json")
)


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_fixtures_present() -> None:
    names = {p.name for p in BUNDLE_FILES}
    assert {"Bundle-bundle-minimal.json", "Bundle-IPS-examples-Bundle-01.json"} <= names


@pytest.mark.parametrize("path", BUNDLE_FILES, ids=lambda p: p.name)
def test_bundle_round_trip(path: Path) -> None:
    raw = _load(path)
    bundle = Bundle.model_validate(raw)
    assert bundle.to_fhir() == raw
    assert json.loads(bundle.to_fhir_json()) == raw


@pytest.mark.parametrize("path", BUNDLE_FILES, ids=lambda p: p.name)
def test_modelled_resources_are_parsed_strictly(path: Path) -> None:
    bundle = Bundle.model_validate(_load(path))
    assert bundle.entry
    for entry in bundle.entry:
        resource = entry.resource
        assert resource is not None
        if resource.resource_type in MODELLED_RESOURCES:
            assert type(resource) is MODELLED_RESOURCES[resource.resource_type]
        else:
            assert isinstance(resource, GenericResource)


def test_unmodelled_resources_fall_back_to_generic() -> None:
    bundle = Bundle.model_validate(
        _load(FIXTURES / "ips-examples/Bundle-IPS-examples-Bundle-01.json")
    )
    assert bundle.entry
    generic = {
        e.resource.resource_type for e in bundle.entry if isinstance(e.resource, GenericResource)
    }
    assert "Observation" in generic
    assert not generic & MODELLED_RESOURCES.keys()


def test_primitive_extension_round_trip() -> None:
    raw = _load(FIXTURES / "ips-examples/Bundle-bundle-minimal.json")
    bundle = Bundle.model_validate(raw)
    assert bundle.entry
    condition = next(e.resource for e in bundle.entry if isinstance(e.resource, Condition))
    assert condition.code is not None
    assert condition.code.coding
    ext = condition.code.coding[0].primitive_extensions
    assert ext is not None
    display_ext = ext["display"]
    assert isinstance(display_ext, PrimitiveElement)
    assert display_ext.extension
    assert display_ext.extension[0].url == "http://hl7.org/fhir/StructureDefinition/translation"


def test_typo_is_rejected() -> None:
    with pytest.raises(ValidationError, match="clinicalStatuss"):
        AllergyIntolerance.model_validate(
            {
                "resourceType": "AllergyIntolerance",
                "patient": {"reference": "urn:uuid:p"},
                "clinicalStatuss": {"text": "active"},
            }
        )


def test_primitive_extension_for_unknown_element_is_rejected() -> None:
    with pytest.raises(ValidationError, match="_dispaly"):
        Coding.model_validate({"code": "x", "_dispaly": {"extension": []}})


def test_wrong_resource_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Patient.model_validate({"resourceType": "Practitioner"})


def test_required_binding_enforced() -> None:
    with pytest.raises(ValidationError):
        Patient.model_validate({"resourceType": "Patient", "gender": "M"})


def test_invalid_date_rejected() -> None:
    with pytest.raises(ValidationError):
        Patient(birth_date="01.05.1972")
    assert Patient(birth_date="1972-05").birth_date == "1972-05"


def test_choice_elements_are_exclusive_and_required() -> None:
    subject = Reference(reference="urn:uuid:p")
    with pytest.raises(ValidationError, match=r"medication\[x\]"):
        MedicationStatement(status="active", subject=subject)
    with pytest.raises(ValidationError, match=r"medication\[x\]"):
        MedicationStatement(
            status="active",
            subject=subject,
            medication_codeable_concept=CodeableConcept(text="x"),
            medication_reference=Reference(reference="urn:uuid:m"),
        )
    with pytest.raises(ValidationError, match=r"onset\[x\]"):
        Condition(subject=subject, onset_date_time="2015", onset_string="childhood")


def test_extension_value_and_nested_are_exclusive() -> None:
    with pytest.raises(ValidationError):
        Extension(
            url="http://example.org/x",
            value_string="a",
            extension=[Extension(url="b", value_code="c")],
        )


def test_constructed_resource_serialises_as_fhir_json() -> None:
    statement = MedicationStatement(
        id="ms1",
        status="active",
        subject=Reference(reference="urn:uuid:p"),
        medication_codeable_concept=CodeableConcept(text="Anastrozole 1 mg tablet", coding=[]),
        identifier=[],
    )
    assert statement.to_fhir() == {
        "resourceType": "MedicationStatement",
        "id": "ms1",
        "status": "active",
        "subject": {"reference": "urn:uuid:p"},
        "medicationCodeableConcept": {"text": "Anastrozole 1 mg tablet"},
    }


def test_decimal_serialised_as_number() -> None:
    assert Quantity(value=Decimal("1")).to_fhir() == {"value": 1}
    assert Quantity(value=Decimal("2.5")).to_fhir() == {"value": 2.5}
    assert Quantity.model_validate({"value": 0.25}).value == Decimal("0.25")


def test_composition_requires_core_elements() -> None:
    with pytest.raises(ValidationError):
        Composition.model_validate({"resourceType": "Composition", "status": "final"})
