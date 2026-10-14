"""Vital Signs section (optional, LOINC 8716-3) -> Observation (category vital-signs).

One Observation per ``VitalSignItem`` with the fixed LOINC code of its kind and a UCUM Quantity
(PLAN.md D-14: hard-coded, no lookup). The LLM gives a number and the unit as written; the unit
is accepted only when it is a known spelling of the kind's unit (``height``: cm, m converted to
cm; ``weight``: kg; ...). A unit that is not recognised is not guessed: the Observation then
carries ``valueString`` (number and unit as written) and a warning note is recorded. BMI, blood
pressure and heart rate may come without a unit (their only unit is implied by the measurement).

Blood pressure is the panel 85354-9 with a systolic and (if stated) a diastolic component.
``effective[x]`` is the stated measurement date. The FHIR vital-signs profiles require a date
precise to the day (``vs-1``; even a data-absent-reason fails it in the validator), so a vital
sign with no date, or only a year or month, is not an Observation: it is kept as a line of the
section narrative and an info note records it. If no vital sign is dated, the section has only
that narrative and ``emptyReason`` ``unavailable``. The section is emitted only when there is
an item.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    fixed_coding,
    fixed_concept,
    section_with_extras,
    urn_uuid,
)
from app.fhir.constants import (
    CATEGORY_VITAL_SIGNS,
    LOINC_BLOOD_PRESSURE,
    LOINC_BMI,
    LOINC_BODY_HEIGHT,
    LOINC_BODY_TEMPERATURE,
    LOINC_BODY_WEIGHT,
    LOINC_DIASTOLIC,
    LOINC_HEART_RATE,
    LOINC_OXYGEN_SATURATION,
    LOINC_OXYGEN_SATURATION_PROFILE,
    LOINC_SYSTOLIC,
    SECTION_VITAL_SIGNS,
    UCUM,
    FixedCode,
)
from app.fhir.models import (
    Annotation,
    CodeableConcept,
    Observation,
    ObservationComponent,
    Quantity,
)
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import Enriched, VitalSignItem, VitalSignKind

KEY = "vital_signs"
TITLE = "Vital Signs"


@dataclass(frozen=True, slots=True)
class _Spec:
    title: str
    code: FixedCode
    ucum: str
    """UCUM code of the Quantity."""
    display_unit: str
    """Human unit (``Quantity.unit``)."""
    aliases: frozenset[str]
    """Accepted spellings (lower-case, spaces removed) of the unit; ``""`` = may be absent."""
    factors: tuple[tuple[str, Decimal], ...] = ()
    """Other units convertible by multiplication: ``(alias, factor)``."""


_MMHG = frozenset({"mmhg", "mm[hg]", "mm(hg)"})
_SPECS: dict[VitalSignKind, _Spec] = {
    VitalSignKind.HEIGHT: _Spec(
        "Body height", LOINC_BODY_HEIGHT, "cm", "cm", frozenset({"cm"}), (("m", Decimal(100)),)
    ),
    VitalSignKind.WEIGHT: _Spec(
        "Body weight", LOINC_BODY_WEIGHT, "kg", "kg", frozenset({"kg", "kg."})
    ),
    VitalSignKind.BODY_MASS_INDEX: _Spec(
        "Body mass index", LOINC_BMI, "kg/m2", "kg/m2", frozenset({"", "kg/m2", "kg/m²", "kg/m^2"})
    ),
    VitalSignKind.BLOOD_PRESSURE: _Spec(
        "Blood pressure", LOINC_BLOOD_PRESSURE, "mm[Hg]", "mmHg", frozenset({""}) | _MMHG
    ),
    VitalSignKind.HEART_RATE: _Spec(
        "Heart rate",
        LOINC_HEART_RATE,
        "/min",
        "/min",
        frozenset({"", "/min", "1/min", "bpm", "permin", "min-1", "/minuutti", "/minut"}),
    ),
    VitalSignKind.BODY_TEMPERATURE: _Spec(
        "Body temperature",
        LOINC_BODY_TEMPERATURE,
        "Cel",
        "°C",
        frozenset({"°c", "c", "cel", "celsius", "℃"}),
    ),
    VitalSignKind.OXYGEN_SATURATION: _Spec(
        "Oxygen saturation",
        LOINC_OXYGEN_SATURATION,
        "%",
        "%",
        frozenset({"%", "prosenttia", "percent"}),
    ),
}


def _unit_key(unit_text: str | None) -> str:
    return "".join((unit_text or "").lower().split())


def _quantity(spec: _Spec, value: Decimal, unit_text: str | None) -> Quantity | None:
    """The UCUM Quantity, or ``None`` if the unit is not a known spelling for the kind."""
    key = _unit_key(unit_text)
    for alias, factor in spec.factors:
        if key == alias:
            return Quantity(
                value=value * factor, unit=spec.display_unit, system=UCUM, code=spec.ucum
            )
    if key in spec.aliases:
        return Quantity(value=value, unit=spec.display_unit, system=UCUM, code=spec.ucum)
    return None


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def map_vital_signs(
    items: list[Enriched[VitalSignItem]], ctx: MappingContext
) -> SectionResult | None:
    if not items:
        return None
    entries: list[MappedResource] = []
    undated: list[NarrativeLine] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(items):
        path = f"{KEY}[{index}]"
        entry, line, item_notes = map_vital_sign(item, path=path, ctx=ctx)
        notes += item_notes
        if entry is None:
            undated.append(line)
        else:
            entries.append(entry)
    section = section_with_extras(SECTION_VITAL_SIGNS, TITLE, entries, undated)
    return SectionResult(section, KEY, entries, notes)


def _day_precise(date: str | None) -> bool:
    """The FHIR vital-signs profiles (vs-1) need a date precise to the day."""
    return date is not None and len(date) >= 10


def map_vital_sign(
    item: Enriched[VitalSignItem], *, path: str, ctx: MappingContext
) -> tuple[MappedResource | None, NarrativeLine, list[MappingNote]]:
    """The Observation (``None`` when the measurement has no day-precise date), the narrative line
    and the mapping notes."""
    v = item.extracted
    spec = _SPECS[v.kind]
    notes: list[MappingNote] = []
    quantity = _quantity(spec, v.value, v.unit_text)
    components: list[ObservationComponent] | None = None
    value_string: str | None = None
    text_value = f"{_plain(v.value)} {v.unit_text or ''}".strip()

    if v.kind is VitalSignKind.BLOOD_PRESSURE:
        systolic = quantity
        diastolic = _quantity(spec, v.diastolic, v.unit_text) if v.diastolic is not None else None
        text_value = _plain(v.value) + (
            f"/{_plain(v.diastolic)}" if v.diastolic is not None else ""
        )
        text_value = f"{text_value} {v.unit_text or ''}".strip()
        if systolic is None or (v.diastolic is not None and diastolic is None):
            value_string = text_value
        else:
            components = [
                ObservationComponent(code=fixed_concept(LOINC_SYSTOLIC), value_quantity=systolic)
            ]
            if diastolic is not None:
                components.append(
                    ObservationComponent(
                        code=fixed_concept(LOINC_DIASTOLIC), value_quantity=diastolic
                    )
                )
            else:
                notes.append(
                    MappingNote(
                        path=path,
                        code=NoteCode.VITAL_SIGN_DIASTOLIC_MISSING,
                        message="Blood pressure without a diastolic value; only the systolic "
                        "component is emitted.",
                    )
                )
        quantity = None
    elif quantity is None:
        value_string = text_value

    if value_string is not None:
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.VITAL_SIGN_UNIT_UNRECOGNISED,
                message="Unit not recognised for this measurement (D-14); the value is kept as "
                "text only.",
            )
        )

    details: list[tuple[str, str]] = [("date", v.effective or "not stated")]
    if v.note:
        details.append(("note", v.note))
    line = NarrativeLine(f"{spec.title}: {text_value}", tuple(details))
    if not _day_precise(v.effective):
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.VITAL_SIGN_NOT_DATED,
                message="No day-precise date: kept in the section narrative only (FHIR vs-1).",
                severity="info",
            )
        )
        return None, line, notes

    code = fixed_concept(spec.code)
    if v.kind is VitalSignKind.OXYGEN_SATURATION:
        code = CodeableConcept(
            coding=[fixed_coding(LOINC_OXYGEN_SATURATION_PROFILE), fixed_coding(spec.code)]
        )
    resource = Observation(
        id=str(item.id),
        text=line_narrative(line),
        status="final",
        category=[fixed_concept(CATEGORY_VITAL_SIGNS)],
        code=code,
        subject=ctx.patient,
        effective_date_time=v.effective,
        value_quantity=quantity,
        value_string=value_string,
        component=components,
        note=[Annotation(text=v.note)] if v.note else None,
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), line, notes
