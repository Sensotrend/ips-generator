"""History of Procedures section (optional, LOINC 47519-4) -> Procedure.

One ``Procedure`` per ``ProcedureItem``: status ``completed`` (the schema holds procedures the
patient has had), ``code`` the text as written plus any lookup coding for ``procedure_text``,
``bodySite`` likewise. ``performed[x]`` is required by the IPS profile: the stated date, or the
string "Date not stated" (as for immunizations; the document date is not a stand-in for the date of
an operation). The section is emitted only when there is an item.
"""

from __future__ import annotations

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    concept,
    entries_section,
    urn_uuid,
)
from app.fhir.constants import PROFILE_PROCEDURE, SECTION_PROCEDURES
from app.fhir.models import Annotation, CodeableConcept, Meta, Procedure
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import Enriched, ProcedureItem

KEY = "procedures"
TITLE = "History of Procedures"
DATE_NOT_STATED = "Date not stated"


def map_procedures(
    items: list[Enriched[ProcedureItem]], ctx: MappingContext
) -> SectionResult | None:
    if not items:
        return None
    entries: list[MappedResource] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(items):
        entry, item_notes = map_procedure(item, path=f"{KEY}[{index}]", ctx=ctx)
        entries.append(entry)
        notes += item_notes
    return SectionResult(entries_section(SECTION_PROCEDURES, TITLE, entries), KEY, entries, notes)


def map_procedure(
    item: Enriched[ProcedureItem], *, path: str, ctx: MappingContext
) -> tuple[MappedResource, list[MappingNote]]:
    p = item.extracted
    notes: list[MappingNote] = []
    code = concept(p.procedure_text, item.codings_for("procedure_text")) or CodeableConcept(
        text=p.procedure_text
    )
    site = (
        concept(p.body_site_text, item.codings_for("body_site_text")) if p.body_site_text else None
    )
    details: list[tuple[str, str]] = []
    if p.body_site_text:
        details.append(("site", p.body_site_text))
    details.append(("date", p.performed or "not stated"))
    if p.note:
        details.append(("note", p.note))
    line = NarrativeLine(p.procedure_text, tuple(details))
    if not p.performed:
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.PROCEDURE_NOT_DATED,
                message="The document gives no date for this procedure.",
                severity="info",
            )
        )
    resource = Procedure(
        id=str(item.id),
        meta=Meta(profile=[PROFILE_PROCEDURE]),
        text=line_narrative(line),
        status="completed",
        code=code,
        subject=ctx.patient,
        performed_date_time=p.performed,
        performed_string=None if p.performed else DATE_NOT_STATED,
        body_site=[site] if site else None,
        note=[Annotation(text=p.note)] if p.note else None,
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), notes
