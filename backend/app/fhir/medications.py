"""Medication Summary section (required) -> MedicationStatement-uv-ips.

* ``items_found``: one MedicationStatement per item with an inline
  ``medicationCodeableConcept`` (no separate Medication resource; validated in the
  ``text-only-codes-inline-medication`` variant). Its ``text`` is the product as written
  (name, strength, dose form); codings are the lookups for ``medication_text``. Lookup codings
  for ``dose_form_text`` have no element here and are reported (``coding_not_emitted``).
* ``none_known``: one MedicationStatement coded 787481004 "No known medications".
* ``no_information``: no entries, ``emptyReason`` = ``unavailable``.

``effective[x]`` is 1..1 in IPS and a missing one is only visible as an unmatched Bundle entry
(PLAN Phase 1 note): stated start/end dates give ``effectivePeriod``; otherwise
``_effectiveDateTime`` carries a data-absent-reason (``unknown``). A period whose start is after
its end (per-1) is not encoded (data-absent-reason + warning; the dates stay in the narrative).

Status: active/completed/stopped/intended map 1:1, ``on_hold`` -> ``on-hold``, ``not_taken`` ->
``not-taken``, ``not_stated`` -> ``unknown``.

Dosage: ``text`` as written; structured parts only where stated: ``doseQuantity`` (value + the
unit as written, no UCUM code: ``tabl`` is not UCUM and a code must not be guessed), timing
``frequency``/``period``/``periodUnit`` only when all three are stated, ``asNeededBoolean`` only
when PRN is stated, ``route`` as text + lookup codings.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    concept,
    data_absent,
    empty_section,
    entries_section,
    fixed_concept,
    printed_code_note,
    urn_uuid,
)
from app.fhir.constants import (
    NO_KNOWN_MEDICATIONS,
    PROFILE_MEDICATION_STATEMENT,
    SECTION_MEDICATIONS,
)
from app.fhir.models import (
    Annotation,
    Dosage,
    DosageDoseAndRate,
    MedicationStatement,
    Meta,
    Period,
    PrimitiveElement,
    Quantity,
    Reference,
    Timing,
    TimingRepeat,
)
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import Dosage as DosageItem
from app.schemas.intermediate import (
    Enriched,
    EnrichedMedicationSection,
    ItemsFound,
    MedicationItem,
    MedicationStatus,
    NoneKnown,
    TimeUnit,
)

KEY = "medications"
TITLE = "Medication Summary"

StatementStatus = Literal[
    "active", "completed", "intended", "stopped", "on-hold", "unknown", "not-taken"
]
STATUS: dict[MedicationStatus, StatementStatus] = {
    MedicationStatus.ACTIVE: "active",
    MedicationStatus.COMPLETED: "completed",
    MedicationStatus.STOPPED: "stopped",
    MedicationStatus.ON_HOLD: "on-hold",
    MedicationStatus.INTENDED: "intended",
    MedicationStatus.NOT_TAKEN: "not-taken",
    MedicationStatus.NOT_STATED: "unknown",
}
_PERIOD_UNIT: dict[TimeUnit, Literal["s", "min", "h", "d", "wk", "mo", "a"]] = {
    TimeUnit.S: "s",
    TimeUnit.MIN: "min",
    TimeUnit.H: "h",
    TimeUnit.D: "d",
    TimeUnit.WK: "wk",
    TimeUnit.MO: "mo",
    TimeUnit.A: "a",
}


def map_medication_section(
    section: EnrichedMedicationSection, ctx: MappingContext
) -> SectionResult:
    if isinstance(section, NoneKnown):
        entry = _known_absent(ctx.new_id(f"{KEY}.none_known"), ctx.patient)
        return SectionResult(entries_section(SECTION_MEDICATIONS, TITLE, [entry]), KEY, [entry])
    if isinstance(section, ItemsFound):
        entries: list[MappedResource] = []
        notes: list[MappingNote] = []
        for index, item in enumerate(section.items):
            entry, item_notes = map_medication(
                item, path=f"{KEY}.items[{index}]", patient=ctx.patient
            )
            entries.append(entry)
            notes += item_notes
        return SectionResult(
            entries_section(SECTION_MEDICATIONS, TITLE, entries), KEY, entries, notes
        )
    return SectionResult(empty_section(SECTION_MEDICATIONS, TITLE), KEY)


def _known_absent(resource_id: UUID, patient: Reference) -> MappedResource:
    line = NarrativeLine(NO_KNOWN_MEDICATIONS.display)
    resource = MedicationStatement(
        id=str(resource_id),
        meta=Meta(profile=[PROFILE_MEDICATION_STATEMENT]),
        text=line_narrative(line),
        status="active",
        medication_codeable_concept=fixed_concept(NO_KNOWN_MEDICATIONS),
        subject=patient,
        primitive_extensions={"effectiveDateTime": data_absent()},
    )
    return MappedResource(KEY, None, urn_uuid(resource_id), resource, line)


def _inverted(start: str, end: str) -> bool:
    """per-1 for partial dates: compare at the shorter precision."""
    n = min(len(start), len(end))
    return start[:n] > end[:n]


def map_medication(
    item: Enriched[MedicationItem], *, path: str, patient: Reference
) -> tuple[MappedResource, list[MappingNote]]:
    m = item.extracted
    notes = printed_code_note(path, m.printed_code)
    if item.codings_for("dose_form_text"):
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.CODING_NOT_EMITTED,
                message="Dose form coding has no element in an inline medication concept; "
                "dose form kept as text.",
                severity="info",
            )
        )

    medication_text = " ".join(
        t for t in (m.medication_text, m.strength_text, m.dose_form_text) if t
    )
    status = STATUS[m.status]
    details: list[tuple[str, str]] = []
    if m.dosage.text:
        details.append(("dosage", m.dosage.text))
    details.append(("status", status))

    period: Period | None = None
    prim: dict[str, PrimitiveElement | list[PrimitiveElement | None]] = {}
    start, end = m.effective_start, m.effective_end
    if start:
        details.append(("start", start))
    if end:
        details.append(("end", end))
    if start and end and _inverted(start, end):
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.MEDICATION_PERIOD_INVERTED,
                message="Start date is after end date; period not encoded (narrative only).",
            )
        )
    elif start or end:
        period = Period(start=start, end=end)
    if period is None:
        prim["effectiveDateTime"] = data_absent()
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.MEDICATION_EFFECTIVE_UNKNOWN,
                message="No usable effective date; effectiveDateTime marked "
                "data-absent-reason 'unknown' (required by IPS).",
                severity="info",
            )
        )

    dosage, dosage_notes = _dosage(m.dosage, item, path)
    notes += dosage_notes
    if m.reason_text:
        details.append(("reason", m.reason_text))
    if m.note:
        details.append(("note", m.note))

    line = NarrativeLine(medication_text, tuple(details))
    resource = MedicationStatement(
        id=str(item.id),
        meta=Meta(profile=[PROFILE_MEDICATION_STATEMENT]),
        text=line_narrative(line),
        status=status,
        medication_codeable_concept=concept(medication_text, item.codings_for("medication_text")),
        subject=patient,
        effective_period=period,
        reason_code=[c for c in [concept(m.reason_text)] if c is not None] or None,
        note=[Annotation(text=m.note)] if m.note else None,
        dosage=[dosage] if dosage else None,
        primitive_extensions=prim or None,
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), notes


def _dosage(
    d: DosageItem, item: Enriched[MedicationItem], path: str
) -> tuple[Dosage | None, list[MappingNote]]:
    notes: list[MappingNote] = []
    timing = None
    unit = _PERIOD_UNIT.get(d.period_unit)
    if d.frequency is not None and d.frequency >= 1 and d.period is not None and unit:
        timing = Timing(
            repeat=TimingRepeat(frequency=d.frequency, period=d.period, period_unit=unit)
        )
    elif d.frequency is not None or d.period is not None or unit:
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.DOSAGE_TIMING_INCOMPLETE,
                message="Frequency, period and period unit are not all stated; timing kept "
                "in dosage text only.",
                severity="info",
            )
        )
    dose = (
        [DosageDoseAndRate(dose_quantity=Quantity(value=d.dose_value, unit=d.dose_unit))]
        if d.dose_value is not None
        else None
    )
    route = concept(d.route_text, item.codings_for("dosage.route_text"))
    as_needed = True if d.as_needed else None
    if all(part is None for part in (d.text, timing, as_needed, route, dose)):
        return None, notes
    dosage = Dosage(
        text=d.text, timing=timing, as_needed_boolean=as_needed, route=route, dose_and_rate=dose
    )
    return dosage, notes
