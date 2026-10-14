"""Thin Pydantic v2 models for the FHIR R4 (4.0.1) resources and datatypes the IPS needs (D-6).

Scope: only the elements the IPS profiles use, plus what is needed to round-trip the HL7 IPS IG
example Bundles. Matchbox (validation against the IPS IG) is the conformance gate; these models
only make the deterministic mappers type-safe and catch structural mistakes early.

Design:

* **Python names are snake_case, JSON names are FHIR camelCase** via an alias generator. Construct
  models with snake_case keyword arguments; parse FHIR JSON with :meth:`FhirBase.model_validate`;
  produce FHIR JSON with :meth:`FhirBase.to_fhir` (or :meth:`FhirBase.to_fhir_json`).
* **``extra="forbid"``** on every modelled type, so a typo or an element we have not modelled fails
  loudly instead of being silently dropped or emitted. The IG examples still round-trip because
  (a) everything they use is modelled and (b) resources we do not model at all (Observation,
  Immunization, PractitionerRole, ...) are carried as :class:`GenericResource`, which keeps the
  raw JSON (``extra="allow"``). Bundle entries are routed by ``resourceType``: modelled types are
  validated strictly, everything else falls back to :class:`GenericResource`.
* **Primitive extensions** (``"_display": {...}`` next to ``"display"``) are accepted on any model
  for any modelled primitive element, kept in :attr:`FhirBase.primitive_extensions` and written back
  out. A ``_name`` without a matching primitive element is rejected (``extra="forbid"`` semantics).
* **Serialisation follows FHIR JSON rules**: ``None`` and empty lists/objects are omitted,
  ``resourceType`` is always emitted, decimals are emitted as JSON numbers.
* Choice elements (``value[x]``) are separate optional fields; validators enforce "at most one"
  (or "exactly one" where the base spec requires it).
* Dates/times are kept as strings validated against the FHIR regexes, so values round-trip
  unchanged (partial dates such as ``2020-07`` are legal FHIR).
* Codes with a *required* binding in R4 are ``Literal`` types; other codes are plain strings.
* Decimals are :class:`~decimal.Decimal` in Python. Trailing zeros (``1.50``) cannot be preserved
  through a JSON number round-trip; values compare equal.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PlainSerializer,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    StringConstraints,
    Tag,
    model_serializer,
    model_validator,
)
from pydantic.alias_generators import to_camel

# --------------------------------------------------------------------------------------------
# Primitive types
# --------------------------------------------------------------------------------------------

_DATE_RE = (
    r"^([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)"
    r"(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|3[0-1]))?)?$"
)
_DATETIME_RE = (
    r"^([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|"
    r"3[0-1])(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?(Z|(\+|-)((0[0-9]|1[0-3]):"
    r"[0-5][0-9]|14:00)))?)?)?$"
)
_INSTANT_RE = (
    r"^([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|"
    r"3[0-1])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?(Z|(\+|-)((0[0-9]|1[0-3]):"
    r"[0-5][0-9]|14:00))$"
)
_TIME_RE = r"^([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?$"

FhirString = Annotated[str, StringConstraints(min_length=1)]
FhirCode = Annotated[str, StringConstraints(pattern=r"^[^\s]+( [^\s]+)*$")]
FhirId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9\-\.]{1,64}$")]
FhirUri = Annotated[str, StringConstraints(pattern=r"^\S*$")]
FhirDate = Annotated[str, StringConstraints(pattern=_DATE_RE)]
FhirDateTime = Annotated[str, StringConstraints(pattern=_DATETIME_RE)]
FhirInstant = Annotated[str, StringConstraints(pattern=_INSTANT_RE)]
FhirTime = Annotated[str, StringConstraints(pattern=_TIME_RE)]
FhirMarkdown = FhirString
PositiveInt = Annotated[StrictInt, Field(ge=1)]
UnsignedInt = Annotated[StrictInt, Field(ge=0)]


def _decimal_to_json(value: Decimal) -> int | float:
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent >= 0:
        return int(value)
    return float(value)


FhirDecimal = Annotated[
    Decimal, PlainSerializer(_decimal_to_json, return_type=int | float, when_used="json")
]

# --------------------------------------------------------------------------------------------
# Base classes
# --------------------------------------------------------------------------------------------


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    """FHIR JSON forbids empty arrays and objects (and nulls, already excluded)."""
    return {k: v for k, v in data.items() if v not in ([], {}, None)}


class FhirBase(BaseModel):
    """Base of every modelled FHIR element: strict keys, camelCase JSON, FHIR serialisation."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
    )

    primitive_extensions: dict[str, PrimitiveElement | list[PrimitiveElement | None]] | None = (
        Field(default=None, exclude=True)
    )
    """Extensions on primitive elements (FHIR ``_name`` JSON keys), keyed by element JSON name."""

    _choice_groups: ClassVar[tuple[tuple[str, tuple[str, ...], bool], ...]] = ()
    """``(element, field names, required)`` for each ``element[x]`` choice of this type."""

    @model_validator(mode="before")
    @classmethod
    def _collect_primitive_extensions(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not any(
            isinstance(k, str) and k.startswith("_") for k in data
        ):
            return data
        aliases = {f.alias or name for name, f in cls.model_fields.items()}
        out: dict[str, Any] = {}
        prim: dict[str, Any] = dict(data.get("primitive_extensions") or {})
        for key, value in data.items():
            if isinstance(key, str) and key.startswith("_"):
                name = key[1:]
                if name not in aliases:
                    raise ValueError(f"primitive extension {key!r} has no element {name!r}")
                prim[name] = value
            else:
                out[key] = value
        out["primitive_extensions"] = prim
        return out

    @model_validator(mode="after")
    def _check_choices(self) -> FhirBase:
        for element, names, required in self._choice_groups:
            present = [n for n in names if getattr(self, n) is not None]
            if len(present) > 1:
                raise ValueError(f"{element}[x]: only one of {names} may be set, got {present}")
            if required and not present:
                raise ValueError(f"{element}[x]: one of {names} is required")
        return self

    @model_serializer(mode="wrap")
    def _serialize(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.primitive_extensions:
            for name, ext in self.primitive_extensions.items():
                if isinstance(ext, list):
                    data[f"_{name}"] = [
                        None if e is None else e.model_dump(mode=info.mode, exclude_none=True)
                        for e in ext
                    ]
                else:
                    data[f"_{name}"] = ext.model_dump(mode=info.mode, exclude_none=True)
        return _drop_empty(data)

    def to_fhir(self) -> dict[str, Any]:
        """Return the FHIR JSON representation as Python objects (dicts/lists/str/numbers)."""
        return self.model_dump(mode="json", exclude_none=True)

    def to_fhir_json(self, *, indent: int | None = None) -> str:
        """Return the FHIR JSON representation as a string."""
        return json.dumps(self.to_fhir(), indent=indent, ensure_ascii=False)


class Element(FhirBase):
    """FHIR Element: ``id`` and ``extension``."""

    id: FhirString | None = None
    extension: list[Extension] | None = None


class PrimitiveElement(Element):
    """The ``_name`` companion object of a primitive element (id + extensions only)."""


class BackboneElement(Element):
    modifier_extension: list[Extension] | None = None


# --------------------------------------------------------------------------------------------
# Datatypes
# --------------------------------------------------------------------------------------------


class Coding(Element):
    system: FhirUri | None = None
    version: FhirString | None = None
    code: FhirCode | None = None
    display: FhirString | None = None
    user_selected: StrictBool | None = None


class CodeableConcept(Element):
    coding: list[Coding] | None = None
    text: FhirString | None = None


class Period(Element):
    start: FhirDateTime | None = None
    end: FhirDateTime | None = None


class Quantity(Element):
    """Quantity (also used for SimpleQuantity, Age, Duration: same JSON shape)."""

    value: FhirDecimal | None = None
    comparator: Literal["<", "<=", ">=", ">"] | None = None
    unit: FhirString | None = None
    system: FhirUri | None = None
    code: FhirCode | None = None


class Range(Element):
    low: Quantity | None = None
    high: Quantity | None = None


class Ratio(Element):
    numerator: Quantity | None = None
    denominator: Quantity | None = None


class Identifier(Element):
    use: Literal["usual", "official", "temp", "secondary", "old"] | None = None
    type: CodeableConcept | None = None
    system: FhirUri | None = None
    value: FhirString | None = None
    period: Period | None = None
    assigner: Reference | None = None


class Reference(Element):
    reference: FhirString | None = None
    type: FhirUri | None = None
    identifier: Identifier | None = None
    display: FhirString | None = None


class HumanName(Element):
    use: Literal["usual", "official", "temp", "nickname", "anonymous", "old", "maiden"] | None = (
        None
    )
    text: FhirString | None = None
    family: FhirString | None = None
    given: list[FhirString] | None = None
    prefix: list[FhirString] | None = None
    suffix: list[FhirString] | None = None
    period: Period | None = None


class ContactPoint(Element):
    system: Literal["phone", "fax", "email", "pager", "url", "sms", "other"] | None = None
    value: FhirString | None = None
    use: Literal["home", "work", "temp", "old", "mobile"] | None = None
    rank: PositiveInt | None = None
    period: Period | None = None


class Address(Element):
    use: Literal["home", "work", "temp", "old", "billing"] | None = None
    type: Literal["postal", "physical", "both"] | None = None
    text: FhirString | None = None
    line: list[FhirString] | None = None
    city: FhirString | None = None
    district: FhirString | None = None
    state: FhirString | None = None
    postal_code: FhirString | None = None
    country: FhirString | None = None
    period: Period | None = None


class Narrative(Element):
    status: Literal["generated", "extensions", "additional", "empty"]
    div: FhirString
    """XHTML ``<div>`` (namespace ``http://www.w3.org/1999/xhtml``); not parsed here."""


class Annotation(Element):
    _choice_groups = (("author", ("author_reference", "author_string"), False),)

    author_reference: Reference | None = None
    author_string: FhirString | None = None
    time: FhirDateTime | None = None
    text: FhirMarkdown


class Meta(Element):
    version_id: FhirId | None = None
    last_updated: FhirInstant | None = None
    source: FhirUri | None = None
    profile: list[FhirUri] | None = None
    security: list[Coding] | None = None
    tag: list[Coding] | None = None


class Extension(Element):
    """Generic extension: ``url`` plus one common-type ``value[x]``, or nested extensions."""

    _choice_groups = (
        (
            "value",
            (
                "value_boolean",
                "value_code",
                "value_date",
                "value_date_time",
                "value_decimal",
                "value_instant",
                "value_integer",
                "value_string",
                "value_uri",
                "value_url",
                "value_canonical",
                "value_codeable_concept",
                "value_coding",
                "value_identifier",
                "value_period",
                "value_quantity",
                "value_range",
                "value_ratio",
                "value_reference",
            ),
            False,
        ),
    )

    url: FhirUri
    value_boolean: StrictBool | None = None
    value_code: FhirCode | None = None
    value_date: FhirDate | None = None
    value_date_time: FhirDateTime | None = None
    value_decimal: FhirDecimal | None = None
    value_instant: FhirInstant | None = None
    value_integer: StrictInt | None = None
    value_string: FhirString | None = None
    value_uri: FhirUri | None = None
    value_url: FhirUri | None = None
    value_canonical: FhirUri | None = None
    value_codeable_concept: CodeableConcept | None = None
    value_coding: Coding | None = None
    value_identifier: Identifier | None = None
    value_period: Period | None = None
    value_quantity: Quantity | None = None
    value_range: Range | None = None
    value_ratio: Ratio | None = None
    value_reference: Reference | None = None

    @model_validator(mode="after")
    def _value_or_extensions(self) -> Extension:
        has_value = any(getattr(self, n) is not None for n in self._choice_groups[0][1])
        if has_value and self.extension:
            raise ValueError("Extension: value[x] and nested extension are mutually exclusive")
        return self


TimeUnit = Literal["s", "min", "h", "d", "wk", "mo", "a"]


class TimingRepeat(Element):
    _choice_groups = (("bounds", ("bounds_duration", "bounds_range", "bounds_period"), False),)

    bounds_duration: Quantity | None = None
    bounds_range: Range | None = None
    bounds_period: Period | None = None
    count: PositiveInt | None = None
    count_max: PositiveInt | None = None
    duration: FhirDecimal | None = None
    duration_max: FhirDecimal | None = None
    duration_unit: TimeUnit | None = None
    frequency: PositiveInt | None = None
    frequency_max: PositiveInt | None = None
    period: FhirDecimal | None = None
    period_max: FhirDecimal | None = None
    period_unit: TimeUnit | None = None
    day_of_week: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] | None = None
    time_of_day: list[FhirTime] | None = None
    when: list[FhirCode] | None = None
    offset: UnsignedInt | None = None


class Timing(BackboneElement):
    event: list[FhirDateTime] | None = None
    repeat: TimingRepeat | None = None
    code: CodeableConcept | None = None


class DosageDoseAndRate(Element):
    _choice_groups = (
        ("dose", ("dose_range", "dose_quantity"), False),
        ("rate", ("rate_ratio", "rate_range", "rate_quantity"), False),
    )

    type: CodeableConcept | None = None
    dose_range: Range | None = None
    dose_quantity: Quantity | None = None
    rate_ratio: Ratio | None = None
    rate_range: Range | None = None
    rate_quantity: Quantity | None = None


class Dosage(BackboneElement):
    _choice_groups = (("asNeeded", ("as_needed_boolean", "as_needed_codeable_concept"), False),)

    sequence: StrictInt | None = None
    text: FhirString | None = None
    additional_instruction: list[CodeableConcept] | None = None
    patient_instruction: FhirString | None = None
    timing: Timing | None = None
    as_needed_boolean: StrictBool | None = None
    as_needed_codeable_concept: CodeableConcept | None = None
    site: CodeableConcept | None = None
    route: CodeableConcept | None = None
    method: CodeableConcept | None = None
    dose_and_rate: list[DosageDoseAndRate] | None = None
    max_dose_per_period: Ratio | None = None
    max_dose_per_administration: Quantity | None = None
    max_dose_per_lifetime: Quantity | None = None


# --------------------------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------------------------


class Resource(FhirBase):
    """Base Resource elements."""

    resource_type: str = Field(alias="resourceType")
    id: FhirId | None = None
    meta: Meta | None = None
    implicit_rules: FhirUri | None = None
    language: FhirCode | None = None


class DomainResource(Resource):
    """DomainResource elements (no ``contained``: not used by the IPS mappers or examples)."""

    text: Narrative | None = None
    extension: list[Extension] | None = None
    modifier_extension: list[Extension] | None = None


class GenericResource(BaseModel):
    """Fallback for resource types not modelled here: keeps the raw JSON unchanged.

    Only ``resourceType`` (and ``id``) are checked; validity is left to Matchbox.
    """

    model_config = ConfigDict(extra="allow", serialize_by_alias=True, validate_by_alias=True)

    resource_type: str = Field(alias="resourceType")
    id: str | None = None

    def to_fhir(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Patient(DomainResource):
    _choice_groups = (
        ("deceased", ("deceased_boolean", "deceased_date_time"), False),
        ("multipleBirth", ("multiple_birth_boolean", "multiple_birth_integer"), False),
    )

    resource_type: Literal["Patient"] = Field(default="Patient", alias="resourceType")
    identifier: list[Identifier] | None = None
    active: StrictBool | None = None
    name: list[HumanName] | None = None
    telecom: list[ContactPoint] | None = None
    gender: Literal["male", "female", "other", "unknown"] | None = None
    birth_date: FhirDate | None = None
    deceased_boolean: StrictBool | None = None
    deceased_date_time: FhirDateTime | None = None
    address: list[Address] | None = None
    marital_status: CodeableConcept | None = None
    multiple_birth_boolean: StrictBool | None = None
    multiple_birth_integer: StrictInt | None = None
    contact: list[PatientContact] | None = None
    communication: list[PatientCommunication] | None = None
    general_practitioner: list[Reference] | None = None
    managing_organization: Reference | None = None


class PatientContact(BackboneElement):
    relationship: list[CodeableConcept] | None = None
    name: HumanName | None = None
    telecom: list[ContactPoint] | None = None
    address: Address | None = None
    gender: Literal["male", "female", "other", "unknown"] | None = None
    organization: Reference | None = None
    period: Period | None = None


class PatientCommunication(BackboneElement):
    language: CodeableConcept
    preferred: StrictBool | None = None


class Organization(DomainResource):
    resource_type: Literal["Organization"] = Field(default="Organization", alias="resourceType")
    identifier: list[Identifier] | None = None
    active: StrictBool | None = None
    type: list[CodeableConcept] | None = None
    name: FhirString | None = None
    alias: list[FhirString] | None = None
    telecom: list[ContactPoint] | None = None
    address: list[Address] | None = None
    part_of: Reference | None = None


class PractitionerQualification(BackboneElement):
    identifier: list[Identifier] | None = None
    code: CodeableConcept
    period: Period | None = None
    issuer: Reference | None = None


class Practitioner(DomainResource):
    resource_type: Literal["Practitioner"] = Field(default="Practitioner", alias="resourceType")
    identifier: list[Identifier] | None = None
    active: StrictBool | None = None
    name: list[HumanName] | None = None
    telecom: list[ContactPoint] | None = None
    address: list[Address] | None = None
    gender: Literal["male", "female", "other", "unknown"] | None = None
    birth_date: FhirDate | None = None
    qualification: list[PractitionerQualification] | None = None
    communication: list[CodeableConcept] | None = None


class DeviceName(BackboneElement):
    name: FhirString
    type: Literal[
        "udi-label-name",
        "user-friendly-name",
        "patient-reported-name",
        "manufacturer-name",
        "model-name",
        "other",
    ]


class DeviceVersion(BackboneElement):
    type: CodeableConcept | None = None
    component: Identifier | None = None
    value: FhirString


class Device(DomainResource):
    resource_type: Literal["Device"] = Field(default="Device", alias="resourceType")
    identifier: list[Identifier] | None = None
    status: Literal["active", "inactive", "entered-in-error", "unknown"] | None = None
    manufacturer: FhirString | None = None
    device_name: list[DeviceName] | None = None
    model_number: FhirString | None = None
    serial_number: FhirString | None = None
    type: CodeableConcept | None = None
    version: list[DeviceVersion] | None = None
    owner: Reference | None = None
    patient: Reference | None = None
    note: list[Annotation] | None = None


class AllergyIntoleranceReaction(BackboneElement):
    substance: CodeableConcept | None = None
    manifestation: list[CodeableConcept]
    description: FhirString | None = None
    onset: FhirDateTime | None = None
    severity: Literal["mild", "moderate", "severe"] | None = None
    exposure_route: CodeableConcept | None = None
    note: list[Annotation] | None = None


class AllergyIntolerance(DomainResource):
    _choice_groups = (
        (
            "onset",
            ("onset_date_time", "onset_age", "onset_period", "onset_range", "onset_string"),
            False,
        ),
    )

    resource_type: Literal["AllergyIntolerance"] = Field(
        default="AllergyIntolerance", alias="resourceType"
    )
    identifier: list[Identifier] | None = None
    clinical_status: CodeableConcept | None = None
    verification_status: CodeableConcept | None = None
    type: Literal["allergy", "intolerance"] | None = None
    category: list[Literal["food", "medication", "environment", "biologic"]] | None = None
    criticality: Literal["low", "high", "unable-to-assess"] | None = None
    code: CodeableConcept | None = None
    patient: Reference
    encounter: Reference | None = None
    onset_date_time: FhirDateTime | None = None
    onset_age: Quantity | None = None
    onset_period: Period | None = None
    onset_range: Range | None = None
    onset_string: FhirString | None = None
    recorded_date: FhirDateTime | None = None
    recorder: Reference | None = None
    asserter: Reference | None = None
    last_occurrence: FhirDateTime | None = None
    note: list[Annotation] | None = None
    reaction: list[AllergyIntoleranceReaction] | None = None


_ONSET_ABATEMENT = ("date_time", "age", "period", "range", "string")


class Condition(DomainResource):
    _choice_groups = (
        ("onset", tuple(f"onset_{s}" for s in _ONSET_ABATEMENT), False),
        (
            "abatement",
            (*(f"abatement_{s}" for s in _ONSET_ABATEMENT),),
            False,
        ),
    )

    resource_type: Literal["Condition"] = Field(default="Condition", alias="resourceType")
    identifier: list[Identifier] | None = None
    clinical_status: CodeableConcept | None = None
    verification_status: CodeableConcept | None = None
    category: list[CodeableConcept] | None = None
    severity: CodeableConcept | None = None
    code: CodeableConcept | None = None
    body_site: list[CodeableConcept] | None = None
    subject: Reference
    encounter: Reference | None = None
    onset_date_time: FhirDateTime | None = None
    onset_age: Quantity | None = None
    onset_period: Period | None = None
    onset_range: Range | None = None
    onset_string: FhirString | None = None
    abatement_date_time: FhirDateTime | None = None
    abatement_age: Quantity | None = None
    abatement_period: Period | None = None
    abatement_range: Range | None = None
    abatement_string: FhirString | None = None
    recorded_date: FhirDateTime | None = None
    recorder: Reference | None = None
    asserter: Reference | None = None
    note: list[Annotation] | None = None


class MedicationIngredient(BackboneElement):
    _choice_groups = (("item", ("item_codeable_concept", "item_reference"), True),)

    item_codeable_concept: CodeableConcept | None = None
    item_reference: Reference | None = None
    is_active: StrictBool | None = None
    strength: Ratio | None = None


class MedicationBatch(BackboneElement):
    lot_number: FhirString | None = None
    expiration_date: FhirDateTime | None = None


class Medication(DomainResource):
    resource_type: Literal["Medication"] = Field(default="Medication", alias="resourceType")
    identifier: list[Identifier] | None = None
    code: CodeableConcept | None = None
    status: Literal["active", "inactive", "entered-in-error"] | None = None
    manufacturer: Reference | None = None
    form: CodeableConcept | None = None
    amount: Ratio | None = None
    ingredient: list[MedicationIngredient] | None = None
    batch: MedicationBatch | None = None


class MedicationStatement(DomainResource):
    _choice_groups = (
        ("medication", ("medication_codeable_concept", "medication_reference"), True),
        ("effective", ("effective_date_time", "effective_period"), False),
    )

    resource_type: Literal["MedicationStatement"] = Field(
        default="MedicationStatement", alias="resourceType"
    )
    identifier: list[Identifier] | None = None
    based_on: list[Reference] | None = None
    part_of: list[Reference] | None = None
    status: Literal[
        "active",
        "completed",
        "entered-in-error",
        "intended",
        "stopped",
        "on-hold",
        "unknown",
        "not-taken",
    ]
    status_reason: list[CodeableConcept] | None = None
    category: CodeableConcept | None = None
    medication_codeable_concept: CodeableConcept | None = None
    medication_reference: Reference | None = None
    subject: Reference
    context: Reference | None = None
    effective_date_time: FhirDateTime | None = None
    effective_period: Period | None = None
    date_asserted: FhirDateTime | None = None
    information_source: Reference | None = None
    derived_from: list[Reference] | None = None
    reason_code: list[CodeableConcept] | None = None
    reason_reference: list[Reference] | None = None
    note: list[Annotation] | None = None
    dosage: list[Dosage] | None = None


class ObservationReferenceRange(BackboneElement):
    low: Quantity | None = None
    high: Quantity | None = None
    type: CodeableConcept | None = None
    applies_to: list[CodeableConcept] | None = None
    age: Range | None = None
    text: FhirString | None = None


_OBSERVATION_VALUE = (
    "value_quantity",
    "value_codeable_concept",
    "value_string",
    "value_boolean",
    "value_integer",
    "value_range",
    "value_ratio",
    "value_time",
    "value_date_time",
    "value_period",
)


class ObservationComponent(BackboneElement):
    _choice_groups = (("value", _OBSERVATION_VALUE, False),)

    code: CodeableConcept
    value_quantity: Quantity | None = None
    value_codeable_concept: CodeableConcept | None = None
    value_string: FhirString | None = None
    value_boolean: StrictBool | None = None
    value_integer: StrictInt | None = None
    value_range: Range | None = None
    value_ratio: Ratio | None = None
    value_time: FhirTime | None = None
    value_date_time: FhirDateTime | None = None
    value_period: Period | None = None
    data_absent_reason: CodeableConcept | None = None
    interpretation: list[CodeableConcept] | None = None
    reference_range: list[ObservationReferenceRange] | None = None


class Observation(DomainResource):
    _choice_groups = (
        ("effective", ("effective_date_time", "effective_period", "effective_instant"), False),
        ("value", _OBSERVATION_VALUE, False),
    )

    resource_type: Literal["Observation"] = Field(default="Observation", alias="resourceType")
    identifier: list[Identifier] | None = None
    based_on: list[Reference] | None = None
    part_of: list[Reference] | None = None
    status: Literal[
        "registered", "preliminary", "final", "amended", "corrected", "cancelled",
        "entered-in-error", "unknown",
    ]  # fmt: skip
    category: list[CodeableConcept] | None = None
    code: CodeableConcept
    subject: Reference | None = None
    focus: list[Reference] | None = None
    encounter: Reference | None = None
    effective_date_time: FhirDateTime | None = None
    effective_period: Period | None = None
    effective_instant: FhirInstant | None = None
    issued: FhirInstant | None = None
    performer: list[Reference] | None = None
    value_quantity: Quantity | None = None
    value_codeable_concept: CodeableConcept | None = None
    value_string: FhirString | None = None
    value_boolean: StrictBool | None = None
    value_integer: StrictInt | None = None
    value_range: Range | None = None
    value_ratio: Ratio | None = None
    value_time: FhirTime | None = None
    value_date_time: FhirDateTime | None = None
    value_period: Period | None = None
    data_absent_reason: CodeableConcept | None = None
    interpretation: list[CodeableConcept] | None = None
    note: list[Annotation] | None = None
    body_site: CodeableConcept | None = None
    method: CodeableConcept | None = None
    specimen: Reference | None = None
    device: Reference | None = None
    reference_range: list[ObservationReferenceRange] | None = None
    has_member: list[Reference] | None = None
    derived_from: list[Reference] | None = None
    component: list[ObservationComponent] | None = None


class Immunization(DomainResource):
    _choice_groups = (("occurrence", ("occurrence_date_time", "occurrence_string"), True),)

    resource_type: Literal["Immunization"] = Field(default="Immunization", alias="resourceType")
    identifier: list[Identifier] | None = None
    status: Literal["completed", "entered-in-error", "not-done"]
    status_reason: CodeableConcept | None = None
    vaccine_code: CodeableConcept
    patient: Reference
    encounter: Reference | None = None
    occurrence_date_time: FhirDateTime | None = None
    occurrence_string: FhirString | None = None
    recorded: FhirDateTime | None = None
    primary_source: StrictBool | None = None
    note: list[Annotation] | None = None


class CompositionAttester(BackboneElement):
    mode: Literal["personal", "professional", "legal", "official"]
    time: FhirDateTime | None = None
    party: Reference | None = None


class CompositionRelatesTo(BackboneElement):
    _choice_groups = (("target", ("target_identifier", "target_reference"), True),)

    code: Literal["replaces", "transforms", "signs", "appends"]
    target_identifier: Identifier | None = None
    target_reference: Reference | None = None


class CompositionEvent(BackboneElement):
    code: list[CodeableConcept] | None = None
    period: Period | None = None
    detail: list[Reference] | None = None


class CompositionSection(BackboneElement):
    title: FhirString | None = None
    code: CodeableConcept | None = None
    author: list[Reference] | None = None
    focus: Reference | None = None
    text: Narrative | None = None
    mode: Literal["working", "snapshot", "changes"] | None = None
    ordered_by: CodeableConcept | None = None
    entry: list[Reference] | None = None
    empty_reason: CodeableConcept | None = None
    section: list[CompositionSection] | None = None


class Composition(DomainResource):
    resource_type: Literal["Composition"] = Field(default="Composition", alias="resourceType")
    identifier: Identifier | None = None
    status: Literal["preliminary", "final", "amended", "entered-in-error"]
    type: CodeableConcept
    category: list[CodeableConcept] | None = None
    subject: Reference | None = None
    encounter: Reference | None = None
    date: FhirDateTime
    author: list[Reference]
    title: FhirString
    confidentiality: Literal["U", "L", "M", "N", "R", "V"] | None = None
    attester: list[CompositionAttester] | None = None
    custodian: Reference | None = None
    relates_to: list[CompositionRelatesTo] | None = None
    event: list[CompositionEvent] | None = None
    section: list[CompositionSection] | None = None


class ProvenanceAgent(BackboneElement):
    type: CodeableConcept | None = None
    role: list[CodeableConcept] | None = None
    who: Reference
    on_behalf_of: Reference | None = None


class ProvenanceEntity(BackboneElement):
    role: Literal["derivation", "revision", "quotation", "source", "removal"]
    what: Reference
    agent: list[ProvenanceAgent] | None = None


class Provenance(DomainResource):
    _choice_groups = (("occurred", ("occurred_period", "occurred_date_time"), False),)

    resource_type: Literal["Provenance"] = Field(default="Provenance", alias="resourceType")
    target: list[Reference]
    occurred_period: Period | None = None
    occurred_date_time: FhirDateTime | None = None
    recorded: FhirInstant
    policy: list[FhirUri] | None = None
    location: Reference | None = None
    reason: list[CodeableConcept] | None = None
    activity: CodeableConcept | None = None
    agent: list[ProvenanceAgent]
    entity: list[ProvenanceEntity] | None = None


# --------------------------------------------------------------------------------------------
# Bundle
# --------------------------------------------------------------------------------------------

MODELLED_RESOURCES: dict[str, type[Resource]] = {
    cls.model_fields["resource_type"].default: cls
    for cls in (
        AllergyIntolerance,
        Composition,
        Condition,
        Device,
        Immunization,
        Medication,
        MedicationStatement,
        Observation,
        Organization,
        Patient,
        Practitioner,
        Provenance,
    )
}
"""resourceType -> model class for every resource modelled strictly here."""

_GENERIC_TAG = "*"


def _resource_tag(value: Any) -> str:
    if isinstance(value, dict):
        rt = value.get("resourceType")
    else:
        rt = getattr(value, "resource_type", None)
    return rt if isinstance(rt, str) and rt in MODELLED_RESOURCES else _GENERIC_TAG


AnyResource = Annotated[
    Annotated[AllergyIntolerance, Tag("AllergyIntolerance")]
    | Annotated[Composition, Tag("Composition")]
    | Annotated[Condition, Tag("Condition")]
    | Annotated[Device, Tag("Device")]
    | Annotated[Immunization, Tag("Immunization")]
    | Annotated[Medication, Tag("Medication")]
    | Annotated[MedicationStatement, Tag("MedicationStatement")]
    | Annotated[Observation, Tag("Observation")]
    | Annotated[Organization, Tag("Organization")]
    | Annotated[Patient, Tag("Patient")]
    | Annotated[Practitioner, Tag("Practitioner")]
    | Annotated[Provenance, Tag("Provenance")]
    | Annotated[GenericResource, Tag(_GENERIC_TAG)],
    Discriminator(_resource_tag),
]
"""A Bundle entry resource: strict model when modelled, :class:`GenericResource` otherwise."""


class BundleLink(BackboneElement):
    relation: FhirString
    url: FhirUri


class BundleEntry(BackboneElement):
    """Bundle.entry (``search``/``request``/``response`` omitted: prohibited in IPS documents)."""

    link: list[BundleLink] | None = None
    full_url: FhirUri | None = None
    resource: AnyResource | None = None


class Bundle(Resource):
    resource_type: Literal["Bundle"] = Field(default="Bundle", alias="resourceType")
    identifier: Identifier | None = None
    type: Literal[
        "document",
        "message",
        "transaction",
        "transaction-response",
        "batch",
        "batch-response",
        "history",
        "searchset",
        "collection",
    ]
    timestamp: FhirInstant | None = None
    total: UnsignedInt | None = None
    link: list[BundleLink] | None = None
    entry: list[BundleEntry] | None = None


for _model in list(globals().values()):
    if isinstance(_model, type) and issubclass(_model, FhirBase):
        _model.model_rebuild()
