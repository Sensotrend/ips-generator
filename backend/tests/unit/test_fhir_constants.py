"""IG-fixed constants (D-1) agree with the HL7 IPS 2.0.1 example Bundles."""

import json
from pathlib import Path
from typing import Any

from app.fhir import constants as c

EXAMPLES = Path(__file__).parents[1] / "fixtures" / "ips-examples"
VARIANTS = Path(__file__).parents[1] / "fixtures" / "ips-variants"


def _composition(path: Path) -> dict[str, Any]:
    bundle: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    composition: dict[str, Any] = bundle["entry"][0]["resource"]
    assert composition["resourceType"] == "Composition"
    return composition


def _as_tuple(coding: dict[str, Any]) -> tuple[str, str, str]:
    return coding["system"], coding["code"], coding["display"]


def _fixed(code: c.FixedCode) -> tuple[str, str, str]:
    return code.system, code.code, code.display


def test_composition_type_matches_examples() -> None:
    for path in EXAMPLES.glob("*.json"):
        assert _as_tuple(_composition(path)["type"]["coding"][0]) == _fixed(c.COMPOSITION_TYPE)


def test_required_section_codes_match_minimal_example() -> None:
    sections = _composition(EXAMPLES / "Bundle-bundle-minimal.json")["section"]
    codes = {_as_tuple(s["code"]["coding"][0]) for s in sections}
    assert codes == {_fixed(s) for s in c.REQUIRED_SECTIONS}


def test_optional_section_codes_match_bundle_01() -> None:
    sections = _composition(EXAMPLES / "Bundle-IPS-examples-Bundle-01.json")["section"]
    codes = {_as_tuple(s["code"]["coding"][0]) for s in sections}
    assert _fixed(c.SECTION_PAST_PROBLEMS) in codes
    assert _fixed(c.SECTION_PLAN_OF_CARE) in codes
    assert _fixed(c.SECTION_RESULTS) in codes


def test_care_provisioning_event_code() -> None:
    event = _composition(EXAMPLES / "Bundle-bundle-minimal.json")["event"][0]
    coding = event["code"][0]["coding"][0]
    assert (coding["system"], coding["code"]) == (
        c.CARE_PROVISIONING_EVENT.system,
        c.CARE_PROVISIONING_EVENT.code,
    )


def test_bundle_profile_matches_example_meta() -> None:
    bundle = json.loads((EXAMPLES / "Bundle-bundle-minimal.json").read_text(encoding="utf-8"))
    assert bundle["meta"]["profile"] == [c.PROFILE_BUNDLE]
    assert c.PROFILE_BUNDLE_VERSIONED.split("|") == [c.PROFILE_BUNDLE, "2.0.1"]


def test_absent_codes_used_in_validated_variants() -> None:
    # Variants validated against IPS 2.0.1 in Matchbox with 0 errors (see test_matchbox.py).
    sections = _composition(VARIANTS / "Bundle-minimal-empty-sections.json")["section"]
    for section in sections:
        assert _as_tuple(section["emptyReason"]["coding"][0]) == _fixed(c.EMPTY_REASON_UNAVAILABLE)

    bundle = json.loads((VARIANTS / "Bundle-minimal-known-absent.json").read_text("utf-8"))
    by_type = {e["resource"]["resourceType"]: e["resource"] for e in bundle["entry"]}
    assert _as_tuple(by_type["AllergyIntolerance"]["code"]["coding"][0]) == _fixed(
        c.NO_KNOWN_ALLERGY
    )
    assert _as_tuple(by_type["Condition"]["code"]["coding"][0]) == _fixed(c.NO_CURRENT_PROBLEMS)
    assert _as_tuple(
        by_type["MedicationStatement"]["medicationCodeableConcept"]["coding"][0]
    ) == _fixed(c.NO_KNOWN_MEDICATIONS)
