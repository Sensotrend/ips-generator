"""Code systems and search scopes for terminology coding (PLAN.md §2 step 5, D2, D-9).

What tx.fhir.org serves (verified 2026-10-13 against ``https://tx.fhir.org/r4``)
-------------------------------------------------------------------------------
* **SNOMED CT** ``http://snomed.info/sct``: International Edition only
  (``.../900000000000207008/version/20250201``). English designations only: ``displayLanguage=sv``
  changes nothing and Finnish/Swedish filter text finds nothing useful, so searches must use
  English terms (PLAN §7 "FI/SV terminology search"). ``ValueSet/$expand`` with ``filter`` works
  on the implicit value sets ``http://snomed.info/sct?fhir_vs`` and ``?fhir_vs=isa/<sctid>``;
  ``?fhir_vs=ecl/...`` is **not** supported (422 "ValueSet not found").
* **IPS value sets are not hosted** (``url=http://hl7.org/fhir/uv/ips/ValueSet/...`` -> 422), but
  ``POST ValueSet/$expand`` with the IPS ``compose`` inline (``Parameters.valueSet``) works for the
  SNOMED, ATC and EDQM ones. Ranking follows include order, so a value set with many includes
  (e.g. ``allergy-reaction-uv-ips``, 31 ``is-a`` roots) ranks poorly: "urticaria" listed
  "Urticarial vasculitis" first. Single-root implicit value sets rank by match quality.
* **LOINC** ``http://loinc.org`` 2.82: ``$expand`` on ``http://loinc.org/vs`` and ``$lookup``.
* **ATC** ``http://www.whocc.no/atc`` (version "2025"): ``$lookup`` works; there is no implicit
  ``?fhir_vs`` value set, but an inline compose ``include: [{system: atc}]`` (= IPS
  ``whoatc-uv-ips``) expands with ``filter`` ("metformin" -> A10BA02 first). English displays.
* **ICD-10 (WHO)** ``http://hl7.org/fhir/sid/icd-10`` (version "2019-covid-expanded"): ``$lookup``
  and ``$validate-code`` work with dotted codes (E11.9 -> "Type 2 diabetes mellitus : Without
  complications"; unknown codes -> 404). ICD-10-CM (``.../icd-10-cm``) also exists but is the US
  modification and is not used. **ICPC-2 is not available** (422 CodeSystem not found).
* **EDQM Standard Terms** ``http://standardterms.edqm.eu`` ("5 February 2025"): ``$lookup`` and
  inline-compose ``$expand`` with the IPS property filters (class PDF/CMT/CDF/PFT, ROA).
* FHIR core value sets ``condition-severity`` and ``route-codes`` (SNOMED) expand by ``url``;
  ``medication-form-codes`` expands to nothing (total 0).
* Operations: ``$expand``, ``$lookup``, ``$validate-code`` (returns ``result`` + the valid
  display), ``$subsumes`` all work. Latency ~0.65 s per call from Finland.

Rate limits / etiquette: tx.fhir.org is HL7's shared test server. No rate-limit headers are
returned and no published limit was found; it is **for development only** (PLAN §4: Snowstorm /
Ontoserver in production). The client therefore sends one request at a time with a minimum
interval, identifies itself with a User-Agent, caches every answer and retries 429/5xx with
backoff (honouring ``Retry-After``).

IPS 2.0.1 bindings (from ``hl7.fhir.uv.ips#2.0.1`` StructureDefinitions; all ``preferred``)
--------------------------------------------------------------------------------------------
=====================================  ==========================================================
AllergyIntolerance.code                allergies-intolerances-uv-ips (SNOMED); candidate whoatc
AllergyIntolerance.reaction.manifest.  allergy-reaction-uv-ips (31 SNOMED clinical-finding roots)
Condition.code                         problems-uv-ips (SNOMED)
Condition.severity                     FHIR condition-severity (SNOMED)
Condition.bodySite                     FHIR body-site (SNOMED << 442083009 = body-site-uv-ips)
Medication(Statement).medication       medication-uv-ips (SNOMED products); candidate whoatc
Medication.form                        FHIR medication-form-codes; candidate medicine-doseform
Dosage.route                           FHIR route-codes (SNOMED); candidate EDQM routes
=====================================  ==========================================================

The ``compose`` definitions below are copied from those IPS ValueSets. Their concept ids are
**search filters** (hierarchy roots), never emitted as codes, so they are not D-1 constants.
Deviation: reaction manifestations search the whole clinical-finding hierarchy (``isa/404684003``)
because the 31-root IPS compose ranks badly on tx.fhir.org; every IPS root is a clinical finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from app.fhir.constants import LOINC, SNOMED_CT

ATC: Final = "http://www.whocc.no/atc"
ICD_10: Final = "http://hl7.org/fhir/sid/icd-10"
"""WHO ICD-10 (not ICD-10-CM)."""
EDQM: Final = "http://standardterms.edqm.eu"


class CodeSystemName(StrEnum):
    """Short names Claude sees instead of URIs (tool inputs/outputs and the final answer)."""

    SNOMED_CT = "snomed_ct"
    LOINC = "loinc"
    ATC = "atc"
    ICD_10 = "icd_10"
    EDQM = "edqm"

    @property
    def uri(self) -> str:
        return _SYSTEM_URIS[self]

    @classmethod
    def from_uri(cls, uri: str) -> CodeSystemName | None:
        for name, value in _SYSTEM_URIS.items():
            if value == uri:
                return name
        return None


_SYSTEM_URIS: Final[dict[CodeSystemName, str]] = {
    CodeSystemName.SNOMED_CT: SNOMED_CT,
    CodeSystemName.LOINC: LOINC,
    CodeSystemName.ATC: ATC,
    CodeSystemName.ICD_10: ICD_10,
    CodeSystemName.EDQM: EDQM,
}

# Code syntax per system: lookups never send free text, and malformed printed codes are not sent.
CODE_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    SNOMED_CT: re.compile(r"^[1-9]\d{5,17}$"),
    LOINC: re.compile(r"^(\d{1,7}-\d|LP\d{1,7}-\d|LA\d{1,7}-\d)$"),
    ATC: re.compile(r"^[A-Z](\d{2}([A-Z]([A-Z](\d{2})?)?)?)?$"),
    ICD_10: re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$"),
    EDQM: re.compile(r"^\d{4,8}$"),
}


class SearchScope(StrEnum):
    """Where a search looks. Each maps to one value set (implicit, FHIR core or inline IPS)."""

    PROBLEM = "problem"
    ALLERGY_SUBSTANCE = "allergy_substance"
    CLINICAL_FINDING = "clinical_finding"
    BODY_STRUCTURE = "body_structure"
    SEVERITY = "severity"
    ROUTE = "route"
    MEDICINAL_PRODUCT = "medicinal_product"
    ATC = "atc"
    DOSE_FORM = "dose_form"
    LOINC = "loinc"

    @property
    def definition(self) -> ScopeDefinition:
        return SCOPES[self]


@dataclass(frozen=True)
class ScopeDefinition:
    """A value set to search: by canonical ``url`` (GET) or inline ``compose`` (POST)."""

    system: str
    description: str
    url: str | None = None
    compose: dict[str, Any] | None = field(default=None, hash=False, compare=False)

    def __post_init__(self) -> None:
        if (self.url is None) == (self.compose is None):
            raise ValueError("a scope has either a url or a compose")


def _snomed_filter(op: str, *roots: str) -> list[dict[str, Any]]:
    return [
        {"system": SNOMED_CT, "filter": [{"property": "concept", "op": op, "value": root}]}
        for root in roots
    ]


def _edqm_include(*classes: str) -> list[dict[str, Any]]:
    return [
        {
            "system": EDQM,
            "filter": [
                {"property": "status", "op": "=", "value": "C"},
                {"property": "class", "op": "=", "value": cls},
                {"property": "domain", "op": "=", "value": "H+V"},
            ],
        }
        for cls in classes
    ]


SCOPES: Final[dict[SearchScope, ScopeDefinition]] = {
    SearchScope.PROBLEM: ScopeDefinition(
        system=SNOMED_CT,
        description="IPS problems-uv-ips: clinical findings, situations, events",
        compose={
            "include": [
                *_snomed_filter("descendent-of", "404684003", "243796009", "272379006"),
                *_snomed_filter("is-a", "160245001"),
            ]
        },
    ),
    SearchScope.ALLERGY_SUBSTANCE: ScopeDefinition(
        system=SNOMED_CT,
        description="IPS allergies-intolerances-uv-ips: substances, products, allergy findings",
        compose={
            "include": [
                *_snomed_filter("descendent-of", "105590001", "373873005", "420134006"),
                *_snomed_filter("is-a", "716186003"),
            ]
        },
    ),
    SearchScope.CLINICAL_FINDING: ScopeDefinition(
        system=SNOMED_CT,
        description="SNOMED clinical findings (reaction manifestations)",
        url=f"{SNOMED_CT}?fhir_vs=isa/404684003",
    ),
    SearchScope.BODY_STRUCTURE: ScopeDefinition(
        system=SNOMED_CT,
        description="FHIR body-site: SNOMED body structures",
        url=f"{SNOMED_CT}?fhir_vs=isa/442083009",
    ),
    SearchScope.SEVERITY: ScopeDefinition(
        system=SNOMED_CT,
        description="FHIR condition-severity",
        url="http://hl7.org/fhir/ValueSet/condition-severity",
    ),
    SearchScope.ROUTE: ScopeDefinition(
        system=SNOMED_CT,
        description="FHIR route-codes (SNOMED routes)",
        url="http://hl7.org/fhir/ValueSet/route-codes",
    ),
    SearchScope.MEDICINAL_PRODUCT: ScopeDefinition(
        system=SNOMED_CT,
        description="IPS medication-uv-ips: SNOMED medicinal products",
        compose={
            "include": [
                *_snomed_filter("descendent-of", "763158003"),
                *_snomed_filter("is-a", "787481004"),
            ],
            "exclude": _snomed_filter("is-a", "787859002"),
        },
    ),
    SearchScope.ATC: ScopeDefinition(
        system=ATC,
        description="IPS whoatc-uv-ips: WHO ATC",
        compose={"include": [{"system": ATC}]},
    ),
    SearchScope.DOSE_FORM: ScopeDefinition(
        system=EDQM,
        description="IPS medicine-doseform: EDQM pharmaceutical dose forms",
        compose={"include": _edqm_include("PDF", "CMT", "CDF", "PFT")},
    ),
    SearchScope.LOINC: ScopeDefinition(
        system=LOINC,
        description="All of LOINC",
        url=f"{LOINC}/vs",
    ),
}


# --------------------------------------------------------------------------------------------
# Printed codes (D-9): which system a printed code belongs to
# --------------------------------------------------------------------------------------------

_SYSTEM_TEXT: Final[dict[str, str]] = {
    "icd10": ICD_10,
    "whoicd10": ICD_10,
    "atc": ATC,
    "snomed": SNOMED_CT,
    "snomedct": SNOMED_CT,
    "sct": SNOMED_CT,
    "loinc": LOINC,
}
_ATC_FULL_RE = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")
_ICD10_UNDOTTED_RE = re.compile(r"^([A-Z]\d{2})(\d{1,2})$")
_STRIP_MARKS_RE = re.compile(r"[\s†‡*+]")  # dagger, double dagger, asterisk, plus


def system_from_text(system_text: str | None) -> str | None:
    """Map a printed system label ("ICD-10", "ATC", key "atc") to a URI; ``None`` if unknown.

    ICD-10-CM / ICPC-2 / national variants are deliberately unknown (not served or not WHO)."""
    if not system_text:
        return None
    key = re.sub(r"[\s\-_.:]", "", system_text.strip().lower())
    key = re.sub(r"(code|koodi|kod)$", "", key) or key
    return _SYSTEM_TEXT.get(key)


def normalise_printed_code(code: str, system: str) -> str | None:
    """Canonical form of a printed code for ``system``, or ``None`` if it is malformed.

    Strips whitespace and ICD dagger/asterisk marks and upper-cases; ICD-10 "E119" -> "E11.9"."""
    text = _STRIP_MARKS_RE.sub("", code).upper()
    if system == ICD_10:
        match = _ICD10_UNDOTTED_RE.fullmatch(text)
        if match:
            text = f"{match.group(1)}.{match.group(2)}"
    pattern = CODE_PATTERNS.get(system)
    if pattern is None or not pattern.fullmatch(text):
        return None
    return text


def infer_printed_system(code: str, *, item_kind: str) -> str | None:
    """System of an unlabelled printed code, from its format and the kind of item.

    Rules (conservative; anything else stays unresolved):
    * a full 7-character ATC code (``A10BA02``) is ATC for any item;
    * on a medication item, a shorter ATC-shaped code (``A10BA``) is ATC;
    * on a condition item, ``A00``-``Z99`` with optional ``.d``/``.dd`` (or undotted) is ICD-10.
    A 3-character code on a medication or allergy item is ambiguous (``J01`` is both an ATC group
    and an ICD-10 category) and stays unresolved unless labelled.
    """
    text = _STRIP_MARKS_RE.sub("", code).upper()
    if _ATC_FULL_RE.fullmatch(text):
        return ATC
    if item_kind == "medication" and CODE_PATTERNS[ATC].fullmatch(text) and len(text) >= 4:
        return ATC
    if item_kind == "condition" and normalise_printed_code(text, ICD_10) is not None:
        return ICD_10
    return None
