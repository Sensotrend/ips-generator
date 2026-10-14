"""History of Pregnancy section (optional, LOINC 10162-6) -> Observations.

IPS profiles (``Composition.section:sectionPregnancyHx``, PLAN.md D-14, fixed codes):

* **status** -> ``Observation-pregnancy-status-uv-ips``: LOINC 82810-3, value SNOMED CT
  pregnant / not pregnant; ``hasMember`` points to the expected-delivery-date Observation;
* **expected delivery date** -> ``Observation-pregnancy-edd-uv-ips``: LOINC 11778-8,
  ``valueDateTime`` (also a section entry, so it is found without the status);
* **deliveries** -> ``Observation-pregnancy-outcome-uv-ips``: LOINC 11640-0 "[#] Births total",
  ``valueQuantity`` (UCUM ``1``).

Facts the IPS has no profile for (PLAN.md D-15) are plain R4 Observations with fixed LOINC codes.
They validate without errors but match no IPS Bundle slice, so the validation gate accepts them
through ``NON_IPS_OBSERVATION_CODES``:

* **last menstrual period** -> LOINC 8665-2, ``valueDateTime``;
* **number of pregnancies** -> LOINC 11996-6 "[#] Pregnancies" (gravidity), ``valueInteger``;
* **deliveries**, besides the IPS outcome above -> LOINC 11977-6 "[#] Parity", ``valueInteger``
  (a second resource for the same item, id derived from the item id; one narrative line).

``effective[x]``: the date stated for the status (``date`` of a ``status`` item); for every other
fact, and a status without a date, the document date as a stand-in (D-15, marked in the narrative,
``note`` and a mapping note); with no day-precise document date either, ``data-absent-reason``
``unknown`` (every IPS pregnancy profile requires ``effective[x]``). A fact without its status,
date or number is not emitted (warning note). The section is emitted only when it has content.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.fhir.common import (
    Effective,
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    data_absent,
    effective_date,
    entries_section,
    fixed_concept,
    urn_uuid,
)
from app.fhir.constants import (
    LOINC_BIRTHS_TOTAL,
    LOINC_EXPECTED_DELIVERY_DATE,
    LOINC_GRAVIDITY,
    LOINC_LAST_MENSTRUAL_PERIOD,
    LOINC_PARITY,
    LOINC_PREGNANCY_STATUS,
    PREGNANCY_STATUS_VALUES,
    PROFILE_PREGNANCY_EDD,
    PROFILE_PREGNANCY_OUTCOME,
    PROFILE_PREGNANCY_STATUS,
    SECTION_PREGNANCY,
    UCUM,
)
from app.fhir.models import Meta, Observation, PrimitiveElement, Quantity, Reference
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import (
    Enriched,
    PregnancyFactItem,
    PregnancyFactKind,
    PregnancyStatus,
)

KEY = "pregnancy"
TITLE = "History of Pregnancy"

_TITLES = {
    PregnancyFactKind.EXPECTED_DELIVERY_DATE: "Expected delivery date",
    PregnancyFactKind.LAST_MENSTRUAL_PERIOD: "Last menstrual period",
    PregnancyFactKind.PREGNANCIES: "Number of pregnancies",
    PregnancyFactKind.DELIVERIES: "Number of deliveries",
}


def _line(fact: PregnancyFactItem, effective: Effective) -> NarrativeLine | None:
    """The fact as a narrative line, ``None`` if it lacks its value."""
    details: list[tuple[str, str]] = []
    if fact.kind is PregnancyFactKind.STATUS:
        if fact.status is PregnancyStatus.NOT_STATED:
            return None
        title = f"Pregnancy status: {PREGNANCY_STATUS_VALUES[fact.status.value].display}"
    elif fact.kind in (
        PregnancyFactKind.EXPECTED_DELIVERY_DATE,
        PregnancyFactKind.LAST_MENSTRUAL_PERIOD,
    ):
        if not fact.date:
            return None
        title = f"{_TITLES[fact.kind]}: {fact.date}"
    else:
        if fact.count is None:
            return None
        title = f"{_TITLES[fact.kind]}: {fact.count}"
    if effective.value is not None:
        # A status's date is when it holds; for the other facts, whose value may be a date
        # itself, it is when they were recorded.
        label = "date" if fact.kind is PregnancyFactKind.STATUS else "recorded"
        details.append((label, effective.detail()[1]))
    if fact.note:
        details.append(("note", fact.note))
    return NarrativeLine(title, tuple(details))


def _effective(fact: PregnancyFactItem, ctx: MappingContext) -> Effective:
    """A status has its own stated date; the other facts' ``date`` is their value, not when they
    were recorded, so they always take the stand-in."""
    return effective_date(fact.date if fact.kind is PregnancyFactKind.STATUS else None, ctx)


def _absent(
    effective: Effective,
) -> dict[str, PrimitiveElement | list[PrimitiveElement | None]] | None:
    """No ``effectiveDateTime`` value: data-absent-reason ``unknown`` (IPS requires it)."""
    return None if effective.value else {"effectiveDateTime": data_absent()}


def map_pregnancy(
    items: list[Enriched[PregnancyFactItem]], ctx: MappingContext
) -> SectionResult | None:
    entries: list[MappedResource] = []
    notes: list[MappingNote] = []
    edd_urls: list[str] = []
    statuses: list[tuple[Enriched[PregnancyFactItem], str, NarrativeLine, Effective]] = []

    for index, item in enumerate(items):
        path = f"{KEY}[{index}]"
        effective = _effective(item.extracted, ctx)
        line = _line(item.extracted, effective)
        if line is None:
            notes.append(
                MappingNote(
                    path=path,
                    code=NoteCode.PREGNANCY_FACT_INCOMPLETE,
                    message="Pregnancy fact without its status, date or number; not emitted.",
                )
            )
            continue
        notes += effective.notes(path)
        kind = item.extracted.kind
        if kind is PregnancyFactKind.STATUS:
            statuses.append((item, path, line, effective))
            continue
        entry = _observation(item, path, line, effective, ctx)
        entries.append(entry)
        if kind is PregnancyFactKind.EXPECTED_DELIVERY_DATE:
            edd_urls.append(entry.full_url)
        elif kind is PregnancyFactKind.DELIVERIES:
            entries.append(_parity(item, path, line, effective, ctx))

    # The status points at the expected delivery dates, and comes first in the section.
    entries = [
        _observation(item, path, line, effective, ctx, members=edd_urls)
        for item, path, line, effective in statuses
    ] + entries
    if not entries:
        return None
    section = entries_section(SECTION_PREGNANCY, TITLE, entries)
    return SectionResult(section, KEY, entries, notes)


def _observation(
    item: Enriched[PregnancyFactItem],
    path: str,
    line: NarrativeLine,
    effective: Effective,
    ctx: MappingContext,
    *,
    members: list[str] | None = None,
) -> MappedResource:
    """The Observation of one fact; ``members`` (status only): fullUrls of the expected delivery
    dates."""
    f = item.extracted
    profile: str | None = None
    value_concept = None
    value_date = None
    value_integer = None
    value_quantity = None
    if f.kind is PregnancyFactKind.STATUS:
        profile, code = PROFILE_PREGNANCY_STATUS, LOINC_PREGNANCY_STATUS
        value_concept = fixed_concept(PREGNANCY_STATUS_VALUES[f.status.value])
    elif f.kind is PregnancyFactKind.EXPECTED_DELIVERY_DATE:
        profile, code, value_date = PROFILE_PREGNANCY_EDD, LOINC_EXPECTED_DELIVERY_DATE, f.date
    elif f.kind is PregnancyFactKind.LAST_MENSTRUAL_PERIOD:
        code, value_date = LOINC_LAST_MENSTRUAL_PERIOD, f.date
    elif f.kind is PregnancyFactKind.PREGNANCIES:
        code, value_integer = LOINC_GRAVIDITY, f.count
    else:
        profile, code = PROFILE_PREGNANCY_OUTCOME, LOINC_BIRTHS_TOTAL
        value_quantity = Quantity(value=Decimal(f.count or 0), system=UCUM, code="1")
    resource = Observation(
        id=str(item.id),
        meta=Meta(profile=[profile]) if profile else None,
        text=line_narrative(line),
        status="final",
        code=fixed_concept(code),
        subject=ctx.patient,
        effective_date_time=effective.value,
        primitive_extensions=_absent(effective),
        value_codeable_concept=value_concept,
        value_date_time=value_date,
        value_integer=value_integer,
        value_quantity=value_quantity,
        has_member=[Reference(reference=url) for url in members or []] or None,
        note=effective.annotations(f.note),
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line)


def _parity(
    item: Enriched[PregnancyFactItem],
    path: str,
    line: NarrativeLine,
    effective: Effective,
    ctx: MappingContext,
) -> MappedResource:
    """The parity Observation of a ``deliveries`` item. Its id is derived from the item id (stable
    across re-assemblies); no narrative line of its own (the outcome's line covers the fact)."""
    resource_id = uuid5(NAMESPACE_URL, f"urn:uuid:{item.id}#parity")
    resource = Observation(
        id=str(resource_id),
        text=line_narrative(line),
        status="final",
        code=fixed_concept(LOINC_PARITY),
        subject=ctx.patient,
        effective_date_time=effective.value,
        primitive_extensions=_absent(effective),
        value_integer=item.extracted.count,
        note=effective.annotations(item.extracted.note),
    )
    return MappedResource(path, item.id, urn_uuid(resource_id), resource, None)
