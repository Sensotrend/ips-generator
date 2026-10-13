"""Codes and canonical URLs fixed by the HL7 IPS Implementation Guide (decision D-1).

Source: ``hl7.fhir.uv.ips`` **2.0.1** (FHIR 4.0.1), package downloaded from
https://packages.fhir.org/hl7.fhir.uv.ips/2.0.1 and checked against:

* ``StructureDefinition-Composition-uv-ips.json``: ``Composition.type`` pattern and each
  ``Composition.section:<slice>.code`` pattern (LOINC). Displays are those used in the IG examples.
* ``ValueSet-*-uv-ips.json``: the IPS 2.0 "known absent" concepts are SNOMED CT situations included
  in each value set (e.g. ``<< 716186003 |No known allergy|``). IPS 1.x had a separate
  ``absent-unknown-uv-ips`` CodeSystem; **it no longer exists in 2.0.1**.
* "No information" is not a code on a resource in 2.0.1: required sections without entries carry
  ``Composition.section.emptyReason`` (constraint ``ips-comp-1``: entry or emptyReason), as in the
  IG example ``Bundle-bundle-no-info-required-sections`` (``list-empty-reason#unavailable``).
  The ``list-empty-reason`` codes were checked against ``hl7.terminology.r4`` 7.2.0 (an IPS
  dependency).

These are the only codes allowed as literals in the codebase. Every other code must come from a
terminology-server lookup (D-2), and the LLM never outputs codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

IPS_VERSION: Final = "2.0.1"
IPS_CANONICAL: Final = "http://hl7.org/fhir/uv/ips"

LOINC: Final = "http://loinc.org"
SNOMED_CT: Final = "http://snomed.info/sct"
LIST_EMPTY_REASON: Final = "http://terminology.hl7.org/CodeSystem/list-empty-reason"
V3_ACT_CLASS: Final = "http://terminology.hl7.org/CodeSystem/v3-ActClass"
V3_OBSERVATION_VALUE: Final = "http://terminology.hl7.org/CodeSystem/v3-ObservationValue"


@dataclass(frozen=True, slots=True)
class FixedCode:
    """A code fixed by the IG: system, code and display."""

    system: str
    code: str
    display: str


# --- Composition --------------------------------------------------------------------------

COMPOSITION_TYPE: Final = FixedCode(LOINC, "60591-5", "Patient summary Document")
"""``Composition.type`` pattern (Composition-uv-ips)."""

CARE_PROVISIONING_EVENT: Final = FixedCode(V3_ACT_CLASS, "PCPR", "care provision")
"""``Composition.event:careProvisioningEvent.code`` pattern."""

AI_ASSERTED: Final = FixedCode(V3_OBSERVATION_VALUE, "AIAST", "Artificial Intelligence asserted")
"""``meta.security`` label on the Composition: AI took part in producing the document. Not an IPS
code: it is the resource-level label of the HL7 *AI Transparency on FHIR* IG."""


# --- Section codes (Composition.section:<slice>.code patterns) ------------------------------
# Required sections (min 1): problems, allergies, medications.
SECTION_PROBLEMS: Final = FixedCode(LOINC, "11450-4", "Problem list - Reported")
SECTION_ALLERGIES: Final = FixedCode(LOINC, "48765-2", "Allergies and adverse reactions Document")
SECTION_MEDICATIONS: Final = FixedCode(LOINC, "10160-0", "History of Medication use Narrative")
# Optional sections (for later phases).
SECTION_IMMUNIZATIONS: Final = FixedCode(LOINC, "11369-6", "History of Immunization note")
SECTION_RESULTS: Final = FixedCode(
    LOINC, "30954-2", "Relevant diagnostic tests/laboratory data note"
)
SECTION_PROCEDURES: Final = FixedCode(LOINC, "47519-4", "History of Procedures Document")
SECTION_MEDICAL_DEVICES: Final = FixedCode(LOINC, "46264-8", "History of medical device use")
SECTION_ADVANCE_DIRECTIVES: Final = FixedCode(LOINC, "42348-3", "Advance healthcare directives")
SECTION_ALERTS: Final = FixedCode(LOINC, "104605-1", "Alert")
SECTION_FUNCTIONAL_STATUS: Final = FixedCode(LOINC, "47420-5", "Functional status assessment note")
SECTION_PAST_PROBLEMS: Final = FixedCode(LOINC, "11348-0", "History of Past illness note")
SECTION_PREGNANCY: Final = FixedCode(LOINC, "10162-6", "History of pregnancies Narrative")
SECTION_PATIENT_STORY: Final = FixedCode(
    LOINC, "81338-6", "Patient Goals, preferences, and priorities for care experience"
)
SECTION_PLAN_OF_CARE: Final = FixedCode(LOINC, "18776-5", "Plan of care note")
SECTION_SOCIAL_HISTORY: Final = FixedCode(LOINC, "29762-2", "Social history note")
SECTION_VITAL_SIGNS: Final = FixedCode(LOINC, "8716-3", "Vital signs note")

REQUIRED_SECTIONS: Final = (SECTION_PROBLEMS, SECTION_ALLERGIES, SECTION_MEDICATIONS)


# --- "Known absent" codes (SNOMED CT, included in the IPS value sets) ---------------------
# Use as the resource code (e.g. AllergyIntolerance.code) when the source states the absence.
NO_KNOWN_ALLERGY: Final = FixedCode(SNOMED_CT, "716186003", "No known allergy")
"""In ValueSet allergies-intolerances-uv-ips (``<< 716186003``)."""
NO_CURRENT_PROBLEMS: Final = FixedCode(SNOMED_CT, "160245001", "No current problems or disability")
"""In ValueSet problems-uv-ips (``<< 160245001``)."""
NO_KNOWN_MEDICATIONS: Final = FixedCode(SNOMED_CT, "787481004", "No known medications")
"""In ValueSet medication-uv-ips (``<< 787481004``)."""
NO_KNOWN_DEVICE_USE: Final = FixedCode(SNOMED_CT, "787483001", "No known device use")
"""In ValueSet medical-devices-uv-ips (``<< 787483001``)."""
NO_KNOWN_PROCEDURES: Final = FixedCode(SNOMED_CT, "787480003", "No known procedures")
"""In ValueSet procedures-uv-ips (``<< 787480003``)."""
NO_KNOWN_IMMUNIZATIONS: Final = FixedCode(SNOMED_CT, "787482006", "No known immunizations")
"""In ValueSet vaccines-uv-ips (``<< 787482006``)."""


# --- Section empty reasons (Composition.section.emptyReason) ------------------------------
# "No information about ..." in IPS 2.0.1 = section without entries + emptyReason.
EMPTY_REASON_UNAVAILABLE: Final = FixedCode(LIST_EMPTY_REASON, "unavailable", "Unavailable")
EMPTY_REASON_NIL_KNOWN: Final = FixedCode(LIST_EMPTY_REASON, "nilknown", "Nil Known")
EMPTY_REASON_NOT_ASKED: Final = FixedCode(LIST_EMPTY_REASON, "notasked", "Not Asked")
EMPTY_REASON_WITHHELD: Final = FixedCode(LIST_EMPTY_REASON, "withheld", "Information Withheld")


# --- Profile canonical URLs (for meta.profile / $validate) ---------------------------------
def _profile(name: str) -> str:
    return f"{IPS_CANONICAL}/StructureDefinition/{name}"


PROFILE_BUNDLE: Final = _profile("Bundle-uv-ips")
PROFILE_COMPOSITION: Final = _profile("Composition-uv-ips")
PROFILE_PATIENT: Final = _profile("Patient-uv-ips")
PROFILE_ALLERGY_INTOLERANCE: Final = _profile("AllergyIntolerance-uv-ips")
PROFILE_CONDITION: Final = _profile("Condition-uv-ips")
PROFILE_MEDICATION_STATEMENT: Final = _profile("MedicationStatement-uv-ips")
PROFILE_MEDICATION_REQUEST: Final = _profile("MedicationRequest-uv-ips")
PROFILE_MEDICATION: Final = _profile("Medication-uv-ips")
PROFILE_DEVICE: Final = _profile("Device-uv-ips")
PROFILE_DEVICE_OBSERVER: Final = _profile("Device-observer-uv-ips")
PROFILE_DEVICE_USE_STATEMENT: Final = _profile("DeviceUseStatement-uv-ips")
PROFILE_ORGANIZATION: Final = _profile("Organization-uv-ips")
PROFILE_PRACTITIONER: Final = _profile("Practitioner-uv-ips")
PROFILE_PRACTITIONER_ROLE: Final = _profile("PractitionerRole-uv-ips")
PROFILE_IMMUNIZATION: Final = _profile("Immunization-uv-ips")
PROFILE_PROCEDURE: Final = _profile("Procedure-uv-ips")

PROFILE_BUNDLE_VERSIONED: Final = f"{PROFILE_BUNDLE}|{IPS_VERSION}"
"""Profile passed to Matchbox ``$validate``."""


# --- Scoped "no known allergy" codes (D-7) -------------------------------------------------
# ValueSet allergies-intolerances-uv-ips includes ``<< 716186003 |No known allergy|``, so its
# descendants are allowed. Each code below was checked with tx.fhir.org (2026-10-08):
# ``CodeSystem/$subsumes?codeA=716186003&codeB=<code>`` -> ``subsumes``; displays are the
# ``$lookup`` preferred terms. 429625007 is also used in the IG example ``Bundle-01``. All three
# validate in Matchbox (IPS 2.0.1) as ``AllergyIntolerance.code``.
NO_KNOWN_DRUG_ALLERGY: Final = FixedCode(SNOMED_CT, "409137002", "No known drug allergy")
NO_KNOWN_FOOD_ALLERGY: Final = FixedCode(SNOMED_CT, "429625007", "No known food allergy")
NO_KNOWN_ENVIRONMENTAL_ALLERGY: Final = FixedCode(
    SNOMED_CT, "428607008", "No known environmental allergy"
)


# --- FHIR R4 core status codes (required bindings) -----------------------------------------
# Not clinical codes: the only values FHIR R4 allows for these elements. Codes and displays
# checked with tx.fhir.org ``CodeSystem/$lookup`` (2026-10-08).
ALLERGY_CLINICAL: Final = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
ALLERGY_VERIFICATION: Final = (
    "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"
)
CONDITION_CLINICAL: Final = "http://terminology.hl7.org/CodeSystem/condition-clinical"
CONDITION_VER_STATUS: Final = "http://terminology.hl7.org/CodeSystem/condition-ver-status"


def _status_codes(system: str, *codes: str) -> dict[str, FixedCode]:
    return {code: FixedCode(system, code, code.capitalize()) for code in codes}


ALLERGY_CLINICAL_STATUS: Final = _status_codes(ALLERGY_CLINICAL, "active", "inactive", "resolved")
ALLERGY_VERIFICATION_STATUS: Final = _status_codes(
    ALLERGY_VERIFICATION, "unconfirmed", "confirmed", "refuted"
)
CONDITION_CLINICAL_STATUS: Final = _status_codes(
    CONDITION_CLINICAL, "active", "recurrence", "relapse", "inactive", "remission", "resolved"
)
CONDITION_VERIFICATION_STATUS: Final = _status_codes(
    CONDITION_VER_STATUS, "unconfirmed", "provisional", "differential", "confirmed", "refuted"
)


# --- Other FHIR core URIs ------------------------------------------------------------------
DATA_ABSENT_REASON_URL: Final = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"
"""FHIR core extension; value from CodeSystem data-absent-reason (e.g. ``unknown``)."""
DATA_ABSENT_UNKNOWN: Final = "unknown"
URI_IDENTIFIER_SYSTEM: Final = "urn:ietf:rfc:3986"
"""Identifier system for identifiers whose value is a URI (FHIR R4 Identifier, e.g. a document
``Bundle.identifier`` with value ``urn:uuid:...``)."""
