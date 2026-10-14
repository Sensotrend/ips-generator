"""History of Pregnancy section (optional, LOINC 10162-6) -> Observations (IPS profiles).

What the IPS can hold (``Composition.section:sectionPregnancyHx``, PLAN.md D-14, fixed codes):

* **status** -> ``Observation-pregnancy-status-uv-ips``: LOINC 82810-3, value SNOMED CT
  pregnant / not pregnant; ``hasMember`` points to the expected-delivery-date Observation;
* **expected delivery date** -> ``Observation-pregnancy-edd-uv-ips``: LOINC 11778-8,
  ``valueDateTime`` (also a section entry, so it is found without the status);
* **deliveries** -> ``Observation-pregnancy-outcome-uv-ips``: LOINC 11640-0 "[#] Births total",
  ``valueQuantity`` (UCUM ``1``).

The IPS has no place for the number of pregnancies or the last menstrual period: those facts
are kept in the section narrative only, with an info note. Every IPS pregnancy profile requires
``effective[x]``: the date stated for the status (``date`` of a ``status`` item), else
``data-absent-reason`` ``unknown``. A fact without its status, date or number is not emitted
(warning note). The section is emitted only when it has content.
"""

from __future__ import annotations

from decimal import Decimal

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    data_absent,
    fixed_concept,
    section_with_extras,
    urn_uuid,
)
from app.fhir.constants import (
    LOINC_BIRTHS_TOTAL,
    LOINC_EXPECTED_DELIVERY_DATE,
    LOINC_PREGNANCY_STATUS,
    PREGNANCY_STATUS_VALUES,
    PROFILE_PREGNANCY_EDD,
    PROFILE_PREGNANCY_OUTCOME,
    PROFILE_PREGNANCY_STATUS,
    SECTION_PREGNANCY,
    UCUM,
)
from app.fhir.models import Annotation, Meta, Observation, PrimitiveElement, Quantity, Reference
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import (
    Enriched,
    PregnancyFactItem,
    PregnancyFactKind,
    PregnancyStatus,
)

KEY = "pregnancy"
TITLE = "History of Pregnancy"

_NARRATIVE_ONLY = {
    PregnancyFactKind.PREGNANCIES: "Number of pregnancies",
    PregnancyFactKind.LAST_MENSTRUAL_PERIOD: "Last menstrual period",
}


def _line(fact: PregnancyFactItem) -> NarrativeLine | None:
    """The fact as a narrative line, ``None`` if it lacks its value."""
    if fact.kind is PregnancyFactKind.STATUS:
        if fact.status is PregnancyStatus.NOT_STATED:
            return None
        details = (("date", fact.date),) if fact.date else ()
        return NarrativeLine(
            f"Pregnancy status: {PREGNANCY_STATUS_VALUES[fact.status.value].display}", details
        )
    if fact.kind in (
        PregnancyFactKind.EXPECTED_DELIVERY_DATE,
        PregnancyFactKind.LAST_MENSTRUAL_PERIOD,
    ):
        if not fact.date:
            return None
        title = (
            "Expected delivery date"
            if fact.kind is PregnancyFactKind.EXPECTED_DELIVERY_DATE
            else _NARRATIVE_ONLY[fact.kind]
        )
        return NarrativeLine(f"{title}: {fact.date}")
    if fact.count is None:
        return None
    title = (
        "Number of deliveries"
        if fact.kind is PregnancyFactKind.DELIVERIES
        else (_NARRATIVE_ONLY[fact.kind])
    )
    return NarrativeLine(f"{title}: {fact.count}", (("note", fact.note),) if fact.note else ())


def _absent(date: str | None) -> dict[str, PrimitiveElement | list[PrimitiveElement | None]] | None:
    """``effectiveDateTime`` has no value: data-absent-reason ``unknown`` (IPS requires it)."""
    return None if date else {"effectiveDateTime": data_absent()}


def map_pregnancy(
    items: list[Enriched[PregnancyFactItem]], ctx: MappingContext
) -> SectionResult | None:
    entries: list[MappedResource] = []
    extra: list[NarrativeLine] = []
    notes: list[MappingNote] = []
    edd_urls: list[str] = []
    status_items: list[tuple[int, Enriched[PregnancyFactItem], NarrativeLine]] = []
    others: list[tuple[int, Enriched[PregnancyFactItem], NarrativeLine]] = []

    for index, item in enumerate(items):
        path = f"{KEY}[{index}]"
        line = _line(item.extracted)
        if line is None:
            notes.append(
                MappingNote(
                    path=path,
                    code=NoteCode.PREGNANCY_FACT_INCOMPLETE,
                    message="Pregnancy fact without its status, date or number; not emitted.",
                )
            )
            continue
        kind = item.extracted.kind
        if kind in _NARRATIVE_ONLY:
            extra.append(line)
            notes.append(
                MappingNote(
                    path=path,
                    code=NoteCode.NOT_REPRESENTABLE_IN_IPS,
                    message="The IPS has no element for this pregnancy fact; kept in the "
                    "section narrative only.",
                    severity="info",
                )
            )
        elif kind is PregnancyFactKind.STATUS:
            status_items.append((index, item, line))
        else:
            others.append((index, item, line))

    # Expected delivery dates and outcomes first (the status points at the dates).
    for index, item, line in others:
        entry = _observation(item, f"{KEY}[{index}]", line, ctx)
        entries.append(entry)
        if item.extracted.kind is PregnancyFactKind.EXPECTED_DELIVERY_DATE:
            edd_urls.append(entry.full_url)
    for index, item, line in status_items:
        entries.insert(0, _observation(item, f"{KEY}[{index}]", line, ctx, members=edd_urls))

    if not entries and not extra:
        return None
    section = section_with_extras(SECTION_PREGNANCY, TITLE, entries, extra)
    return SectionResult(section, KEY, entries, notes)


def _observation(
    item: Enriched[PregnancyFactItem],
    path: str,
    line: NarrativeLine,
    ctx: MappingContext,
    *,
    members: list[str] | None = None,
) -> MappedResource:
    f = item.extracted
    note = [Annotation(text=f.note)] if f.note else None
    resource: Observation
    if f.kind is PregnancyFactKind.STATUS:
        resource = Observation(
            id=str(item.id),
            meta=Meta(profile=[PROFILE_PREGNANCY_STATUS]),
            text=line_narrative(line),
            status="final",
            code=fixed_concept(LOINC_PREGNANCY_STATUS),
            subject=ctx.patient,
            value_codeable_concept=fixed_concept(PREGNANCY_STATUS_VALUES[f.status.value]),
            has_member=[Reference(reference=url) for url in members or []] or None,
            note=note,
            effective_date_time=f.date,
            primitive_extensions=_absent(f.date),
        )
    elif f.kind is PregnancyFactKind.EXPECTED_DELIVERY_DATE:
        resource = Observation(
            id=str(item.id),
            meta=Meta(profile=[PROFILE_PREGNANCY_EDD]),
            text=line_narrative(line),
            status="final",
            code=fixed_concept(LOINC_EXPECTED_DELIVERY_DATE),
            subject=ctx.patient,
            value_date_time=f.date,
            note=note,
            primitive_extensions=_absent(None),
        )
    else:
        resource = Observation(
            id=str(item.id),
            meta=Meta(profile=[PROFILE_PREGNANCY_OUTCOME]),
            text=line_narrative(line),
            status="final",
            code=fixed_concept(LOINC_BIRTHS_TOTAL),
            subject=ctx.patient,
            value_quantity=Quantity(value=Decimal(f.count or 0), system=UCUM, code="1"),
            note=note,
            primitive_extensions=_absent(None),
        )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line)
