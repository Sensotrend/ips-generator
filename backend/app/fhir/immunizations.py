"""Immunizations section (optional, LOINC 11369-6) -> Immunization.

``vaccineCode`` = the vaccine text as written, plus a code when the text names a vaccine of the
small provisional table (PLAN.md D-14: ATC, hard-coded; MMR, varicella, influenza, COVID-19 mRNA,
tetanus alone) or when the terminology step coded ``vaccine_text``. Combination vaccines
(diphtheria-tetanus-pertussis, ...) are never coded as their tetanus component; vaccines not in
the table stay text only (an info note). ``occurrence[x]`` is the stated date or the string
"Date not stated" (R4 requires one). The section is emitted only when there is an item.
"""

from __future__ import annotations

import re

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    concept,
    entries_section,
    fixed_coding,
    urn_uuid,
)
from app.fhir.constants import (
    SECTION_IMMUNIZATIONS,
    VACCINE_COVID19_MRNA,
    VACCINE_INFLUENZA,
    VACCINE_MMR,
    VACCINE_TETANUS,
    VACCINE_VARICELLA,
    FixedCode,
)
from app.fhir.models import Annotation, CodeableConcept, Immunization
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import Enriched, ImmunizationItem, ImmunizationStatus

KEY = "immunizations"
TITLE = "Immunizations"
DATE_NOT_STATED = "Date not stated"

_COMBINATION = re.compile(
    r"kurkkumät|difteri|diphther|hinkuysk|pertussis|kikhosta|polio|\b(?:dtp|dtap|tdap|dt)\b",
    re.IGNORECASE,
)
_TABLE: tuple[tuple[re.Pattern[str], FixedCode], ...] = (
    (
        re.compile(r"\b(?:mpr|mmr)\b|tuhkarokko|morbilli|measles|mässling", re.IGNORECASE),
        VACCINE_MMR,
    ),
    (re.compile(r"vesirokko|varicella|vattkoppor|chickenpox", re.IGNORECASE), VACCINE_VARICELLA),
    (re.compile(r"influenss|influensa|influenza|\bflu\b", re.IGNORECASE), VACCINE_INFLUENZA),
    (re.compile(r"covid|koronarokot|korona-?rokot|sars-?cov", re.IGNORECASE), VACCINE_COVID19_MRNA),
    (re.compile(r"tetanus|jäykkäkouristus|stelkramp", re.IGNORECASE), VACCINE_TETANUS),
)


def vaccine_code(text: str) -> FixedCode | None:
    """The D-14 hard-coded vaccine code for ``text``, or ``None`` (text only)."""
    if _COMBINATION.search(text):
        return None
    for pattern, code in _TABLE:
        if pattern.search(text):
            return code
    return None


def map_immunizations(
    items: list[Enriched[ImmunizationItem]], ctx: MappingContext
) -> SectionResult | None:
    if not items:
        return None
    entries: list[MappedResource] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(items):
        entry, item_notes = map_immunization(item, path=f"{KEY}[{index}]", ctx=ctx)
        entries.append(entry)
        notes += item_notes
    return SectionResult(
        entries_section(SECTION_IMMUNIZATIONS, TITLE, entries), KEY, entries, notes
    )


def map_immunization(
    item: Enriched[ImmunizationItem], *, path: str, ctx: MappingContext
) -> tuple[MappedResource, list[MappingNote]]:
    i = item.extracted
    notes: list[MappingNote] = []
    looked_up = item.codings_for("vaccine_text")
    fixed = None if looked_up else vaccine_code(i.vaccine_text)
    if fixed is not None:
        vaccine = CodeableConcept(coding=[fixed_coding(fixed)], text=i.vaccine_text)
    else:
        vaccine = concept(i.vaccine_text, looked_up) or CodeableConcept(text=i.vaccine_text)
        if not looked_up:
            notes.append(
                MappingNote(
                    path=path,
                    code=NoteCode.IMMUNIZATION_NOT_CODED,
                    message="Vaccine is not in the provisional code table (D-14); text only.",
                    severity="info",
                )
            )
    not_done = i.status is ImmunizationStatus.NOT_DONE
    details: list[tuple[str, str]] = [("status", "not done" if not_done else "completed")]
    details.append(("date", i.occurrence or DATE_NOT_STATED.lower()))
    if i.note:
        details.append(("note", i.note))
    line = NarrativeLine(i.vaccine_text, tuple(details))
    resource = Immunization(
        id=str(item.id),
        text=line_narrative(line),
        status="not-done" if not_done else "completed",
        vaccine_code=vaccine,
        patient=ctx.patient,
        occurrence_date_time=i.occurrence,
        occurrence_string=None if i.occurrence else DATE_NOT_STATED,
        note=[Annotation(text=i.note)] if i.note else None,
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), notes
