"""Results section (optional, LOINC 30954-2) -> Observation (laboratory or exam).

One Observation per ``ResultItem``. The test is the text as written plus any code the terminology
step found for ``test_text`` (never a code from the model; PLAN.md D-1): with no lookup the code is
text only. A number becomes ``valueQuantity`` with the unit as written (no UCUM code: the unit is
free text from the document) and the comparator ("above 90" -> ``>``); text such as "positive" is
``valueString``. A result with neither has a ``data-absent-reason`` of ``unknown`` and a warning.

Only laboratory results become Observations (IPS ``Observation-results-laboratory-pathology``,
category ``laboratory``). Other tests (spirometry, bone density) have no IPS profile: they stay
lines of the section narrative, with an info note. The profile requires a ``performer`` that the
documents do not give: it carries a ``data-absent-reason`` of ``unknown``. ``effective[x]`` is
required by the profile: the stated date, else the
document date as a stand-in (PLAN.md D-15, marked in the narrative, ``note`` and a mapping note),
else ``data-absent-reason`` ``unknown``. The section is emitted only when there is an item; with
only non-laboratory tests it has just the narrative and ``emptyReason`` ``unavailable``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    concept,
    data_absent,
    effective_date,
    fixed_concept,
    section_with_extras,
    urn_uuid,
)
from app.fhir.constants import (
    CATEGORY_LABORATORY,
    DATA_ABSENT_REASON_SYSTEM,
    DATA_ABSENT_REASON_URL,
    DATA_ABSENT_UNKNOWN,
    SECTION_RESULTS,
)
from app.fhir.models import CodeableConcept, Coding, Extension, Observation, Quantity, Reference
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import Enriched, ResultCategory, ResultItem, ValueComparator

KEY = "results"
TITLE = "Results"

_COMPARATORS: dict[ValueComparator, Literal["<", "<=", ">=", ">"]] = {
    ValueComparator.LESS: "<",
    ValueComparator.AT_MOST: "<=",
    ValueComparator.AT_LEAST: ">=",
    ValueComparator.GREATER: ">",
}


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def map_results(items: list[Enriched[ResultItem]], ctx: MappingContext) -> SectionResult | None:
    if not items:
        return None
    entries: list[MappedResource] = []
    narrative_only: list[NarrativeLine] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(items):
        entry, line, item_notes = map_result(item, path=f"{KEY}[{index}]", ctx=ctx)
        notes += item_notes
        if entry is None:
            narrative_only.append(line)
        else:
            entries.append(entry)
    section = section_with_extras(SECTION_RESULTS, TITLE, entries, narrative_only)
    return SectionResult(section, KEY, entries, notes)


def map_result(
    item: Enriched[ResultItem], *, path: str, ctx: MappingContext
) -> tuple[MappedResource | None, NarrativeLine, list[MappingNote]]:
    """The Observation (``None`` for a test that is not a laboratory one), the narrative line and
    the mapping notes."""
    r = item.extracted
    notes: list[MappingNote] = []
    code = concept(r.test_text, item.codings_for("test_text")) or CodeableConcept(text=r.test_text)

    quantity: Quantity | None = None
    value_string: str | None = None
    shown: str
    if r.value is not None:
        comparator = _COMPARATORS.get(r.comparator)
        quantity = Quantity(value=r.value, comparator=comparator, unit=r.unit_text)
        shown = f"{comparator or ''}{_plain(r.value)} {r.unit_text or ''}".strip()
        if r.unit_text:
            notes.append(
                MappingNote(
                    path=path,
                    code=NoteCode.RESULT_UNIT_NOT_CODED,
                    message="The unit is the text written in the document; no UCUM code.",
                    severity="info",
                )
            )
    elif r.value_text:
        value_string = f"{r.value_text} {r.unit_text or ''}".strip()
        shown = value_string
    else:
        shown = "no value stated"
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.RESULT_WITHOUT_VALUE,
                message="The result has neither a number nor a text value.",
            )
        )

    effective = effective_date(r.effective, ctx)
    details: list[tuple[str, str]] = [("result", shown), effective.detail()]
    if r.note:
        details.append(("note", r.note))
    line = NarrativeLine(r.test_text, tuple(details))
    if r.category is not ResultCategory.LABORATORY:
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.NOT_REPRESENTABLE_IN_IPS,
                message="Only laboratory results have an IPS profile; this test is kept in the "
                "section narrative only.",
                severity="info",
            )
        )
        return None, line, notes
    absent = effective.value is None
    resource = Observation(
        id=str(item.id),
        text=line_narrative(line),
        status="final",
        category=[fixed_concept(CATEGORY_LABORATORY)],
        code=code,
        subject=ctx.patient,
        performer=[
            Reference(
                display="Performer not stated",
                extension=[Extension(url=DATA_ABSENT_REASON_URL, value_code="unknown")],
            )
        ],
        effective_date_time=effective.value,
        primitive_extensions={"effectiveDateTime": data_absent()} if absent else None,
        value_quantity=quantity,
        value_string=value_string,
        data_absent_reason=(
            None
            if quantity is not None or value_string is not None
            else CodeableConcept(
                coding=[Coding(system=DATA_ABSENT_REASON_SYSTEM, code=DATA_ABSENT_UNKNOWN)]
            )
        ),
        note=effective.annotations(r.note),
    )
    notes += effective.notes(path)
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), line, notes
