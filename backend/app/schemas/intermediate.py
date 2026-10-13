"""Intermediate schema between source documents and the IPS FHIR Bundle (PLAN.md D1-D3, D7).

Two layers
----------
1. **LLM extraction layer** (``IpsExtraction`` and everything it contains) is exactly what Claude
   fills via structured outputs (``extraction_output_format()``). It has **no code fields**: no
   SNOMED/LOINC/ATC codes, no FHIR system URIs (CLAUDE.md, D2, D-1). Clinical concepts are kept as
   original-language text (documents are FI/SV/EN; nothing is translated). Field ``description``s
   are part of the prompt.
2. **Enriched layer** (``EnrichedIps``) wraps every extracted item in ``Enriched[...]``, which adds
   a stable ``id`` and ``codings`` filled *only* by the terminology step, each with lookup
   provenance. FHIR mappers in ``app/fhir/`` consume this layer and never the raw LLM output.
   ``EnrichedIps.from_extraction()`` converts layer 1 to layer 2 (no codings yet).

Provenance
----------
Every extracted fact (item, patient name, identifier, birth date, gender, "none known" statement,
including the scoped statements inside allergies ``items_found``) carries ``source_quote``
(verbatim substring of the ingested text, checked by ``ground.py``), ``page`` and ``locator``
that point into ``app.schemas.source.SourceSegment``, plus ``confidence``
(``high``/``medium``/``low``: categorical rather than a float, because LLM-stated probabilities
are poorly calibrated, numeric bounds are not enforceable in structured outputs, and three levels
map directly to review-UI treatment and eval thresholds). Sub-parts of an item (reactions, dosage)
share the item's quote.

``page`` / ``locator`` for non-paged inputs: ``page`` is 1-based and is ``1`` for plaintext, JSON
and CSV. ``locator`` is copied verbatim from the segment that contains the start of the quote
(``"line 12"``, ``"row 4"``, ``"$.medications[2].name"``); empty when that segment has none (e.g.
a PDF page). The extraction prompt must show each segment's page and locator to the model.

Required sections (D7)
----------------------
Each required section is a tagged union on ``kind``, enforced by the structured-output grammar
and validated in Python as a discriminated union (errors are reported for the chosen variant only):

* ``items_found`` - ``items`` has at least one entry (``minItems: 1``). For allergies it also
  carries ``none_known_statements`` (D-7): scoped "no known ..." statements made next to the
  entries, e.g. "NKDA" next to a peanut allergy (``minItems: 0``, so grounding can drop one);
* ``none_known`` - the document *explicitly* states none (e.g. "Ei tiedossa olevia allergioita",
  "NKDA"), with its own ``source_quote``; allergies also record the scope (all/medication/...);
* ``no_information`` - the document says nothing about the topic.

So an empty list can never stand for "none known" or "not documented". Only allergies have
scoped statements: IPS has no scoped "no known ..." concept for medications or problems.

Printed codes (D-9)
-------------------
Allergy, medication and condition items have ``printed_code`` / ``printed_code_system_text``: a
code *printed in the document* next to the entry ("E11.9", "ICD-10"), copied verbatim, never
supplied from model knowledge. ``ground.py`` clears it (and flags the item) unless it occurs in
the item's ``source_quote``. It stays a text *hint* in the enriched layer: it is not codable, so
it never becomes a ``TerminologyCoding``; the terminology step may use it only if the server
confirms that the code exists and matches the text.

Structured-output constraints (Claude JSON schema subset)
---------------------------------------------------------
Every object has ``additionalProperties: false`` and **every property is required** (the API caps
optional properties at 24 and union-typed properties at 16 per request). Hence:

* absent scalar text/dates/numbers are the empty string ``""`` in the LLM JSON; validators turn
  ``""`` into ``None`` on the Python side (the schema still says ``string``);
* "not stated" for closed value sets is an explicit enum member ``not_stated``;
* ``anyOf`` is used only for the three sections and for optional ``birth_date`` / ``gender``
  (5 unions; Phase 2 sections add one each). Pydantic renders the discriminated section unions
  as ``oneOf``; ``extraction_json_schema()`` emits them as ``anyOf`` (the ``kind`` consts make the
  branches disjoint anyway);
* no ``minimum``/``maxLength``-style keywords; numeric/format rules are validated in Python. Enum
  values are matched case-insensitively because structured outputs do not guarantee their casing.

Adding a section (Phase 2): define an ``...Item`` model with the provenance fields and a
``codable_paths`` ClassVar, a ``...Section`` alias built like ``MedicationSection`` (tagged
``ItemsFound[Item] | NoneKnown | NoInformation`` with ``_SECTION_KIND``), a field on
``IpsExtraction`` and the enriched counterpart on ``EnrichedIps``.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    WithJsonSchema,
    model_validator,
)

SCHEMA_VERSION = "1.1.1"
"""Bump when the LLM-facing schema changes (together with the extraction prompt version)."""

# --------------------------------------------------------------------------------------------
# Scalar types
# --------------------------------------------------------------------------------------------

_PARTIAL_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_DECIMAL_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_INT_RE = re.compile(r"^\d+$")


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _normalise_enum(value: Any) -> Any:
    """Structured outputs may change enum casing; accept ``Not stated`` for ``not_stated``."""
    if isinstance(value, str):
        return value.strip().lower().replace(" ", "_").replace("-", "_")
    return value


def _check_partial_date(value: str | None) -> str | None:
    if value is None:
        return None
    match = _PARTIAL_DATE_RE.fullmatch(value)
    if match is None:
        raise ValueError("date must be YYYY, YYYY-MM or YYYY-MM-DD")
    year, month, day = match.groups()
    try:
        dt.date(int(year), int(month or 1), int(day or 1))
    except ValueError as exc:
        raise ValueError(f"not a valid calendar date: {value}") from exc
    return value


def _parse_decimal(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not _DECIMAL_RE.fullmatch(text):
            raise ValueError("must be a plain non-negative number such as 1 or 0.5")
        try:
            return Decimal(text.replace(",", "."))
        except InvalidOperation as exc:  # pragma: no cover - regex already guards this
            raise ValueError("not a number") from exc
    return value


def _parse_int(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not _INT_RE.fullmatch(text):
            raise ValueError("must be a whole number such as 3")
        return int(text)
    return value


def _check_positive(value: int) -> int:
    if value < 1:
        raise ValueError("must be >= 1")
    return value


def _check_not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be empty")
    return value


def _json_string(pattern: str | None = None) -> WithJsonSchema:
    schema: dict[str, Any] = {"type": "string"}
    if pattern is not None:
        schema["pattern"] = pattern
    return WithJsonSchema(schema)


NonEmptyText = Annotated[str, AfterValidator(_check_not_blank)]
"""Required text; must not be blank."""

OptionalText = Annotated[str | None, BeforeValidator(_empty_to_none), _json_string()]
"""Text that may be absent: ``""`` in the LLM JSON, ``None`` in Python."""

PartialDate = Annotated[
    str | None,
    BeforeValidator(_empty_to_none),
    AfterValidator(_check_partial_date),
    _json_string(r"^(\d{4}(-\d{2}(-\d{2})?)?)?$"),
]
"""FHIR-style partial date (YYYY, YYYY-MM, YYYY-MM-DD); ``""``/``None`` when not stated."""

RequiredPartialDate = Annotated[
    str, AfterValidator(_check_partial_date), _json_string(r"^\d{4}(-\d{2}(-\d{2})?)?$")
]

OptionalDecimal = Annotated[
    Decimal | None,
    BeforeValidator(_parse_decimal),
    BeforeValidator(_empty_to_none),  # runs first (validators apply right-to-left)
    _json_string(r"^(\d+([.,]\d+)?)?$"),
]
OptionalInt = Annotated[
    int | None,
    BeforeValidator(_parse_int),
    BeforeValidator(_empty_to_none),
    _json_string(r"^(\d+)?$"),
]
PageNumber = Annotated[int, AfterValidator(_check_positive)]

# --------------------------------------------------------------------------------------------
# Closed value sets (FHIR required bindings), plus ``not_stated``
# --------------------------------------------------------------------------------------------


class _ClosedSet(StrEnum):
    """Enum matched case-insensitively (structured outputs do not guarantee enum casing)."""

    @classmethod
    def _missing_(cls, value: object) -> _ClosedSet | None:
        normalised = _normalise_enum(value)
        for member in cls:
            if member.value == normalised:
                return member
        return None


class Confidence(_ClosedSet):
    """high: explicit and unambiguous. medium: stated, but some interpretation was needed
    (abbreviation, typo, layout). low: unclear wording, illegible or doubtful whether it
    applies to this patient."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AdministrativeGender(_ClosedSet):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class AllergyType(_ClosedSet):
    ALLERGY = "allergy"
    INTOLERANCE = "intolerance"
    NOT_STATED = "not_stated"


class AllergyCategory(_ClosedSet):
    FOOD = "food"
    MEDICATION = "medication"
    ENVIRONMENT = "environment"
    BIOLOGIC = "biologic"
    NOT_STATED = "not_stated"


class AllergyCriticality(_ClosedSet):
    LOW = "low"
    HIGH = "high"
    UNABLE_TO_ASSESS = "unable_to_assess"
    NOT_STATED = "not_stated"


class AllergyClinicalStatus(_ClosedSet):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RESOLVED = "resolved"
    NOT_STATED = "not_stated"


class AllergyVerificationStatus(_ClosedSet):
    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    NOT_STATED = "not_stated"


class Severity(_ClosedSet):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    NOT_STATED = "not_stated"


class MedicationStatus(_ClosedSet):
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ON_HOLD = "on_hold"
    INTENDED = "intended"
    NOT_TAKEN = "not_taken"
    NOT_STATED = "not_stated"


class TimeUnit(_ClosedSet):
    # UCUM units of time allowed by FHIR Timing.repeat.periodUnit.

    S = "s"
    MIN = "min"
    H = "h"
    D = "d"
    WK = "wk"
    MO = "mo"
    A = "a"
    NOT_STATED = "not_stated"


class ConditionClinicalStatus(_ClosedSet):
    ACTIVE = "active"
    RECURRENCE = "recurrence"
    RELAPSE = "relapse"
    INACTIVE = "inactive"
    REMISSION = "remission"
    RESOLVED = "resolved"
    NOT_STATED = "not_stated"


class ConditionVerificationStatus(_ClosedSet):
    UNCONFIRMED = "unconfirmed"
    PROVISIONAL = "provisional"
    DIFFERENTIAL = "differential"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    NOT_STATED = "not_stated"


class AllergyScope(_ClosedSet):
    ALL = "all"
    MEDICATION = "medication"
    FOOD = "food"
    ENVIRONMENT = "environment"


# --------------------------------------------------------------------------------------------
# Provenance field definitions (shared so every fact describes them identically)
# --------------------------------------------------------------------------------------------

_LLM_CONFIG = ConfigDict(extra="forbid")


def _source_quote() -> Any:
    return Field(
        description=(
            "Exact verbatim copy of the shortest contiguous source text that supports this fact, "
            "in the original language. Do not translate, paraphrase, expand abbreviations or fix "
            "typos. Write it before filling the other fields."
        )
    )


def _page() -> Any:
    return Field(description="1-based page of the quote; 1 for non-paged inputs.")


def _locator() -> Any:
    return Field(
        description=(
            "Locator of the segment where the quote starts, copied exactly as shown "
            '(e.g. "line 12", "row 4", "$.medications[2].name"); "" if none is shown.'
        )
    )


def _confidence() -> Any:
    return Field(description="How certain this extraction is.")


def _printed_code() -> Any:
    return Field(
        description=(
            "Code printed in the document next to this entry, copied character for character "
            '(e.g. "E11.9", "A10BA02"); it must also appear in source_quote. "" if no code is '
            "printed. Never supply a code yourself, even if you know it."
        )
    )


def _printed_code_system_text() -> Any:
    return Field(
        description=(
            'System of printed_code as named inside source_quote (e.g. "ICD-10", "ATC", a key '
            '"atc"); "" if the quote does not name it or printed_code is "".'
        )
    )


def _note() -> Any:
    return Field(
        description=(
            "Other clinically relevant text about this item that fits no other field, "
            'as written; "" if none.'
        )
    )


# --------------------------------------------------------------------------------------------
# LLM extraction layer: Patient
# --------------------------------------------------------------------------------------------


class PatientName(BaseModel):
    """One name of the patient as written in the document."""

    model_config = _LLM_CONFIG

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    text: NonEmptyText = Field(description="Full name exactly as written.")
    family: OptionalText = Field(description='Family name(s); "" if it cannot be told apart.')
    given: list[NonEmptyText] = Field(description="Given names in order; [] if not identifiable.")
    confidence: Confidence = _confidence()


class PatientIdentifier(BaseModel):
    """A patient identifier printed in the document (personal identity code, MRN, ...)."""

    model_config = _LLM_CONFIG

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    value: NonEmptyText = Field(description="The identifier exactly as written.")
    type_text: OptionalText = Field(
        description=(
            'Label the document gives the identifier, as written (e.g. "Henkilötunnus", '
            '"Personnummer", "MRN"); "" if unlabelled. Never invent a system or URI.'
        )
    )
    issuer_text: OptionalText = Field(
        description='Organisation that issued it, if stated; "" otherwise.'
    )
    confidence: Confidence = _confidence()


class BirthDate(BaseModel):
    """The patient's date of birth as stated in the document."""

    model_config = _LLM_CONFIG

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    value: RequiredPartialDate = Field(
        description="Birth date as YYYY-MM-DD, or YYYY-MM / YYYY if only that much is stated."
    )
    confidence: Confidence = _confidence()


class Gender(BaseModel):
    """The patient's administrative gender, only when the document states it."""

    model_config = _LLM_CONFIG

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    value: AdministrativeGender = Field(description="Administrative gender as stated.")
    confidence: Confidence = _confidence()


class PatientExtraction(BaseModel):
    """The subject of the document. Extract only what is written; do not derive values."""

    model_config = _LLM_CONFIG

    names: list[PatientName] = Field(description="Patient names; [] if none is given.")
    birth_date: BirthDate | None = Field(description="null if no birth date is stated.")
    gender: Gender | None = Field(description="null if gender is not stated.")
    identifiers: list[PatientIdentifier] = Field(description="Patient identifiers; [] if none.")


# --------------------------------------------------------------------------------------------
# LLM extraction layer: items of the required sections
# --------------------------------------------------------------------------------------------


class AllergyReaction(BaseModel):
    """One reaction the patient had to the substance."""

    model_config = _LLM_CONFIG

    manifestations: list[NonEmptyText] = Field(
        description='Signs/symptoms as written, one per entry (e.g. "urtikaria", "anafylaksia").'
    )
    severity: Severity = Field(description="Severity of this reaction if stated.")


class AllergyItem(BaseModel):
    """One allergy or intolerance of the patient (one substance per item)."""

    model_config = _LLM_CONFIG
    codable_paths: ClassVar[frozenset[str]] = frozenset(
        {"substance_text", "reactions[*].manifestations[*]"}
    )

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    substance_text: NonEmptyText = Field(
        description="The substance, drug or drug class as written (original language), "
        'without an "allergy"/"-allergia" ending or any printed code.'
    )
    printed_code: OptionalText = _printed_code()
    printed_code_system_text: OptionalText = _printed_code_system_text()
    type: AllergyType = Field(
        description="allergy or intolerance, only if worded so for this entry (not a heading)."
    )
    category: AllergyCategory = Field(
        description="Kind of substance; may be inferred from the substance itself."
    )
    criticality: AllergyCriticality = Field(
        description="Risk of a future life-threatening reaction, only if stated for this entry."
    )
    clinical_status: AllergyClinicalStatus = Field(description="Only if stated for this entry.")
    verification_status: AllergyVerificationStatus = Field(
        description="confirmed/unconfirmed (e.g. 'suspected')/refuted, only if worded so for "
        "this entry, never from a heading."
    )
    onset: PartialDate = Field(description='YYYY, YYYY-MM or YYYY-MM-DD; "" if not stated.')
    reactions: list[AllergyReaction] = Field(description="Reactions described; [] if none.")
    note: OptionalText = _note()
    confidence: Confidence = _confidence()


class Dosage(BaseModel):
    """How the medication is taken. Fill structured parts only if they express the
    instruction exactly; otherwise leave them empty and rely on text."""

    model_config = _LLM_CONFIG

    text: OptionalText = Field(
        description="Dosage instruction exactly as written, including any indication in it "
        '(e.g. "1 x 2", "1 tarv. kipuun"); "" if none.'
    )
    dose_value: OptionalDecimal = Field(
        description='Amount per administration as a plain number (e.g. "1", "0.5"); "" if not '
        "a single stated number."
    )
    dose_unit: OptionalText = Field(
        description='Unit the dose counts as written (e.g. "tabl", "puffs", "ml"), or the dose '
        'form next to a bare count; never the strength unit. "" if none.'
    )
    frequency: OptionalInt = Field(
        description='Number of administrations per period (e.g. "2"; "1" for one time of day '
        'such as "aamulla" in a regular dose); "" if not stated.'
    )
    period: OptionalDecimal = Field(
        description='Length of the period, e.g. "1" for "twice a day"; "" if not stated.'
    )
    period_unit: TimeUnit = Field(description="Unit of period.")
    as_needed: bool = Field(
        description="true only if stated as taken as needed (PRN, tarvittaessa) or only on a "
        'stated trigger ("vid anafylaxi").'
    )
    route_text: OptionalText = Field(
        description='Route as written (e.g. "p.o.", "suun kautta"); "" if not stated.'
    )


class MedicationItem(BaseModel):
    """One medication the patient takes, took or is to take (one product per item)."""

    model_config = _LLM_CONFIG
    codable_paths: ClassVar[frozenset[str]] = frozenset(
        {"medication_text", "dose_form_text", "dosage.route_text"}
    )

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    medication_text: NonEmptyText = Field(
        description="Product or substance name as written, without strength, dose form, dosage "
        "or printed code; a mass right after the name is strength_text."
    )
    printed_code: OptionalText = _printed_code()
    printed_code_system_text: OptionalText = _printed_code_system_text()
    strength_text: OptionalText = Field(
        description='Strength as written (e.g. "500 mg", "10 mg/ml"); "" if not stated.'
    )
    dose_form_text: OptionalText = Field(
        description='Dose form as written (e.g. "tabl", "depottabletti"); "" if not stated.'
    )
    dosage: Dosage
    status: MedicationStatus = Field(
        description="active = currently taken; completed/stopped = no longer taken. May follow "
        "from the list the entry is in; the entry's own wording wins."
    )
    effective_start: PartialDate = Field(description='Start date if stated; "" otherwise.')
    effective_end: PartialDate = Field(description='End/stop date if stated; "" otherwise.')
    reason_text: OptionalText = Field(
        description='Indication as written; "" if not stated. It is not also a problem.'
    )
    note: OptionalText = _note()
    confidence: Confidence = _confidence()


class ConditionItem(BaseModel):
    """One problem or diagnosis of the patient, or a presenting symptom no diagnosis explains."""

    model_config = _LLM_CONFIG
    codable_paths: ClassVar[frozenset[str]] = frozenset(
        {"condition_text", "body_site_text", "severity"}
    )

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    condition_text: NonEmptyText = Field(
        description="The problem or diagnosis as written, without any printed code."
    )
    printed_code: OptionalText = _printed_code()
    printed_code_system_text: OptionalText = _printed_code_system_text()
    clinical_status: ConditionClinicalStatus = Field(
        description="active, resolved, etc., only from wording about this entry, never a "
        "heading; not_stated for a listed condition without status wording."
    )
    verification_status: ConditionVerificationStatus = Field(
        description="e.g. 'suspected' = provisional, 'ruled out' = refuted; only if stated for "
        "this entry."
    )
    severity: Severity = Field(description="Only if stated.")
    body_site_text: OptionalText = Field(
        description="Laterality, or a site written as a modifier, as written; a site the "
        'diagnosis name needs stays in condition_text. "" if none.'
    )
    onset: PartialDate = Field(description='YYYY, YYYY-MM or YYYY-MM-DD; "" if not stated.')
    abatement: PartialDate = Field(description='Date resolved, if stated; "" otherwise.')
    note: OptionalText = _note()
    confidence: Confidence = _confidence()


# --------------------------------------------------------------------------------------------
# Section variants (D7)
# --------------------------------------------------------------------------------------------


class ItemsFound[ItemT: BaseModel](BaseModel):
    """The document lists one or more entries for this section."""

    model_config = _LLM_CONFIG

    kind: Annotated[Literal["items_found"], BeforeValidator(_normalise_enum)]
    items: list[ItemT] = Field(
        min_length=1, description="Every distinct entry, once each, in document order."
    )


class _NoneKnownTag(BaseModel):
    model_config = _LLM_CONFIG

    kind: Annotated[Literal["none_known"], BeforeValidator(_normalise_enum)]


class _Statement(BaseModel):
    model_config = _LLM_CONFIG

    source_quote: NonEmptyText = _source_quote()
    page: PageNumber = _page()
    locator: OptionalText = _locator()
    confidence: Confidence = _confidence()


# Pydantic orders inherited fields from the last base to the first: ``kind`` comes first.
class NoneKnown(_Statement, _NoneKnownTag):
    """The document explicitly states there are none (e.g. "no regular medication")."""


class NoKnownAllergyStatement(_Statement):
    """An explicit statement that the patient has no known allergies of some scope (e.g.
    "NKDA", "Ei tiedossa olevia allergioita")."""

    scope: AllergyScope = Field(
        description="What the statement covers, e.g. NKDA = medication; unspecified = all."
    )


class NoKnownAllergies(NoKnownAllergyStatement, _NoneKnownTag):
    """The document explicitly states no known allergies (e.g. "NKDA", "Ei tiedossa olevia
    allergioita")."""


class AllergiesFound[ItemT: BaseModel](ItemsFound[ItemT]):
    """The document lists one or more allergies or intolerances, possibly next to scoped
    "no known ..." statements (e.g. "NKDA" alongside a food allergy)."""

    none_known_statements: list[NoKnownAllergyStatement] = Field(
        description='Explicit "no known ..." statements made alongside the entries (e.g. "NKDA" '
        'next to a food allergy); not "no other known allergies". [] if none.'
    )


class NoInformation(BaseModel):
    """The document says nothing about this topic. Use only when no entry and no explicit
    "none" statement exist."""

    model_config = _LLM_CONFIG

    kind: Annotated[Literal["no_information"], BeforeValidator(_normalise_enum)]


def _section_kind(value: Any) -> str | None:
    """Tag of a section: ``kind`` matched case-insensitively, as for the enums."""
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return _normalise_enum(kind) if isinstance(kind, str) else None


_SECTION_KIND = Discriminator(
    _section_kind,
    custom_error_type="invalid_section_kind",
    custom_error_message='kind must be "items_found", "none_known" or "no_information"',
)
"""Discriminated section unions: errors are reported for the chosen variant only, with a fixed
message (no input value) when ``kind`` is missing or unknown."""

_FOUND = Tag("items_found")
_NONE = Tag("none_known")
_NO_INFO = Tag("no_information")

AllergySection = Annotated[
    Annotated[AllergiesFound[AllergyItem], _FOUND]
    | Annotated[NoKnownAllergies, _NONE]
    | Annotated[NoInformation, _NO_INFO],
    _SECTION_KIND,
]
MedicationSection = Annotated[
    Annotated[ItemsFound[MedicationItem], _FOUND]
    | Annotated[NoneKnown, _NONE]
    | Annotated[NoInformation, _NO_INFO],
    _SECTION_KIND,
]
ProblemSection = Annotated[
    Annotated[ItemsFound[ConditionItem], _FOUND]
    | Annotated[NoneKnown, _NONE]
    | Annotated[NoInformation, _NO_INFO],
    _SECTION_KIND,
]


class IpsExtraction(BaseModel):
    """Facts about one patient extracted from one healthcare document."""

    model_config = _LLM_CONFIG

    document_language: NonEmptyText = Field(
        description='Main language of the document as a BCP 47 tag: "fi", "sv", "en", ...'
    )
    patient: PatientExtraction
    allergies: AllergySection = Field(
        description="Allergies and intolerances, including adverse drug reactions."
    )
    medications: MedicationSection = Field(
        description="Medications currently or recently taken, and those prescribed now."
    )
    problems: ProblemSection = Field(
        description="The patient's problems and diagnoses, current and past, and presenting "
        "symptoms no diagnosis explains. Exclude family history, other people's conditions, "
        "procedures, findings without a written diagnosis and medication indications."
    )


def extraction_json_schema() -> dict[str, Any]:
    """JSON schema of ``IpsExtraction`` for ``output_config.format``.

    Post-processed from Pydantic's schema: titles removed, discriminated ``oneOf`` emitted as
    ``anyOf`` (without ``discriminator``), enum ``$defs`` inlined so that no ``$ref`` has sibling
    keywords (field descriptions would otherwise sit next to ``$ref``).
    Prefer this over ``messages.parse(output_format=IpsExtraction)``: the SDK's transform drops
    descriptions next to ``$ref`` and moves ``pattern`` into the description, while the API
    grammar supports ``pattern``. Validate responses with ``IpsExtraction.model_validate_json``.
    """
    schema: dict[str, Any] = _strip_titles(_any_of_unions(IpsExtraction.model_json_schema()))
    defs: dict[str, Any] = schema.pop("$defs", {})
    enum_defs = {name: d for name, d in defs.items() if d.get("type") != "object"}
    schema = _inline_refs(schema, enum_defs)
    object_defs = {
        name: _inline_refs(d, enum_defs) for name, d in defs.items() if name not in enum_defs
    }
    if object_defs:
        schema["$defs"] = object_defs
    return schema


def extraction_output_format() -> dict[str, Any]:
    """Value for the Messages API ``output_config.format`` parameter."""
    return {"type": "json_schema", "schema": extraction_json_schema()}


def _strip_titles(node: Any) -> Any:
    """Drop ``title``s and collapse docstring line breaks in ``description``s."""
    if isinstance(node, dict):
        return {
            key: " ".join(value.split()) if key == "description" else _strip_titles(value)
            for key, value in node.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [_strip_titles(value) for value in node]
    return node


def _any_of_unions(node: Any) -> Any:
    """``oneOf`` -> ``anyOf`` and drop ``discriminator`` (neither is in the supported subset)."""
    if isinstance(node, dict):
        return {
            ("anyOf" if key == "oneOf" else key): _any_of_unions(value)
            for key, value in node.items()
            if key != "discriminator"
        }
    if isinstance(node, list):
        return [_any_of_unions(value) for value in node]
    return node


def _inline_refs(node: Any, inline: dict[str, Any]) -> Any:
    """Replace ``$ref``s to the given defs by their content; field keywords win, descriptions
    are concatenated (field description first)."""
    if isinstance(node, list):
        return [_inline_refs(value, inline) for value in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.removeprefix("#/$defs/") in inline:
        target = dict(inline[ref.removeprefix("#/$defs/")])
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        descriptions = [d for d in (siblings.get("description"), target.get("description")) if d]
        merged = {**target, **siblings}
        if descriptions:
            merged["description"] = " ".join(descriptions)
        return merged
    return {key: _inline_refs(value, inline) for key, value in node.items()}


# --------------------------------------------------------------------------------------------
# Enriched layer (filled by the terminology step; consumed by the FHIR mappers)
# --------------------------------------------------------------------------------------------


class CodingSelectedBy(StrEnum):
    TOOL_LOOP = "tool_loop"  # Claude chose among terminology-server candidates
    REVIEWER = "reviewer"  # a human picked or confirmed it in review
    DETERMINISTIC = "deterministic"  # exact/unique server match, no model involved


class TerminologyLookup(BaseModel):
    """Where a code came from. Every code must come from a terminology-server response."""

    model_config = ConfigDict(extra="forbid")

    server: NonEmptyText  # base URL of the terminology server
    operation: NonEmptyText  # e.g. "ValueSet/$expand", "CodeSystem/$lookup"
    query: NonEmptyText  # search text sent (may be an English rendering of the source text)
    selected_by: CodingSelectedBy
    model: str | None = None  # model id when selected_by == tool_loop
    retrieved_at: dt.datetime

    @model_validator(mode="after")
    def _model_for_tool_loop(self) -> TerminologyLookup:
        if self.selected_by is CodingSelectedBy.TOOL_LOOP and not self.model:
            raise ValueError("model is required when selected_by is tool_loop")
        return self


def _check_uri(value: str) -> str:
    if not re.match(r"^(https?://|urn:(oid|uuid):)\S+$", value):
        raise ValueError("system must be a canonical URI (http(s)://... or urn:oid/urn:uuid)")
    return value


class TerminologyCoding(BaseModel):
    """A code returned by a terminology server for one text field."""

    model_config = ConfigDict(extra="forbid")

    system: Annotated[str, AfterValidator(_check_uri)]  # e.g. http://snomed.info/sct
    version: str | None = None
    code: NonEmptyText
    display: NonEmptyText
    lookup: TerminologyLookup


class FieldCoding(BaseModel):
    """Codes for one text field of an extracted item, addressed by ``path``.

    ``path`` uses attribute names and list indexes, e.g. ``"substance_text"`` or
    ``"reactions[0].manifestations[1]"``; it must match one of the item's ``codable_paths``.
    """

    model_config = ConfigDict(extra="forbid")

    path: NonEmptyText
    codings: list[TerminologyCoding] = Field(min_length=1)


_PATH_SEGMENT_RE = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?$")


def resolve_path(item: BaseModel, path: str) -> object:
    """Return the value at ``path`` (see ``FieldCoding``) inside ``item``."""
    current: object = item
    for part in path.split("."):
        match = _PATH_SEGMENT_RE.fullmatch(part)
        if match is None:
            raise ValueError(f"invalid path segment {part!r} in {path!r}")
        name, index = match.groups()
        if not isinstance(current, BaseModel) or name not in type(current).model_fields:
            raise ValueError(f"unknown field {name!r} in {path!r}")
        current = getattr(current, name)
        if index is not None:
            if not isinstance(current, list) or int(index) >= len(current):
                raise ValueError(f"index {index} out of range in {path!r}")
            current = current[int(index)]
    return current


def path_pattern(path: str) -> str:
    """``"reactions[0].manifestations[1]"`` -> ``"reactions[*].manifestations[*]"``."""
    return re.sub(r"\[\d+\]", "[*]", path)


class Enriched[ItemT: BaseModel](BaseModel):
    """An extracted item plus a stable id and terminology codes.

    ``printed_code`` (D-9) stays a text hint on ``extracted``; it is not in ``codable_paths``,
    so it can never be turned into a ``TerminologyCoding`` here."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)  # stable across review edits; mappers use urn:uuid
    extracted: ItemT
    codings: list[FieldCoding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_codings(self) -> Self:
        allowed: frozenset[str] = getattr(type(self.extracted), "codable_paths", frozenset())
        seen: set[str] = set()
        for field_coding in self.codings:
            path = field_coding.path
            if path in seen:
                raise ValueError(f"duplicate codings for {path!r}")
            seen.add(path)
            if path_pattern(path) not in allowed:
                raise ValueError(f"{path!r} is not codable for {type(self.extracted).__name__}")
            value = resolve_path(self.extracted, path)
            if not isinstance(value, str) or value in {"", Severity.NOT_STATED}:
                raise ValueError(f"{path!r} has no stated text to code")
        return self

    def codings_for(self, path: str) -> list[TerminologyCoding]:
        """Codes for ``path``; ``[]`` means text only (no code found or not yet coded)."""
        for field_coding in self.codings:
            if field_coding.path == path:
                return field_coding.codings
        return []


EnrichedAllergySection = Annotated[
    Annotated[AllergiesFound[Enriched[AllergyItem]], _FOUND]
    | Annotated[NoKnownAllergies, _NONE]
    | Annotated[NoInformation, _NO_INFO],
    _SECTION_KIND,
]
EnrichedMedicationSection = Annotated[
    Annotated[ItemsFound[Enriched[MedicationItem]], _FOUND]
    | Annotated[NoneKnown, _NONE]
    | Annotated[NoInformation, _NO_INFO],
    _SECTION_KIND,
]
EnrichedProblemSection = Annotated[
    Annotated[ItemsFound[Enriched[ConditionItem]], _FOUND]
    | Annotated[NoneKnown, _NONE]
    | Annotated[NoInformation, _NO_INFO],
    _SECTION_KIND,
]


class EnrichedIps(BaseModel):
    """Extraction plus terminology codes: the input of the FHIR mappers and the review UI."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    document_language: NonEmptyText
    patient: PatientExtraction
    allergies: EnrichedAllergySection
    medications: EnrichedMedicationSection
    problems: EnrichedProblemSection

    @classmethod
    def from_extraction(cls, extraction: IpsExtraction) -> EnrichedIps:
        """Wrap every extracted item (fresh ids, no codings yet)."""
        return cls.model_validate(
            {
                "document_language": extraction.document_language,
                "patient": extraction.patient,
                "allergies": _wrap_items(extraction.allergies),
                "medications": _wrap_items(extraction.medications),
                "problems": _wrap_items(extraction.problems),
            }
        )


def _wrap_items(section: BaseModel) -> object:
    """Wrap ``items``; other fields (e.g. allergies' ``none_known_statements``) carry over."""
    if isinstance(section, ItemsFound):
        fields = {name: getattr(section, name) for name in type(section).model_fields}
        return {**fields, "items": [{"extracted": item} for item in section.items]}
    return section
