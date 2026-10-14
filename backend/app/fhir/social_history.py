"""Social History section (optional, LOINC 29762-2).

* **Tobacco** -> ``Observation-tobaccouse-uv-ips``: LOINC 72166-2 "Tobacco smoking status" with a
  SNOMED CT value for the status the LLM filled (never / former / current / non-smoker;
  PLAN.md D-14, hard-coded); with no clear status the value is the text as written. The text the
  document used is the concept's ``text``. ``effective[x]`` is required by the profile: the stated
  date (e.g. when smoking stopped), else the document date as a stand-in (PLAN.md D-15, marked in
  the narrative, ``note`` and a mapping note), else ``data-absent-reason`` ``unknown``.
* **Alcohol**: the IPS profile (``Observation-alcoholuse-uv-ips``, LOINC 74013-4) is a number of
  drinks per day. Free text such as "uses little alcohol" cannot be that, so alcohol facts are
  kept in the section narrative only, with an info note.

The section is emitted only when there is an item; with only alcohol facts it has just the
narrative and ``emptyReason`` ``unavailable``.
"""

from __future__ import annotations

from app.fhir.common import (
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    data_absent,
    effective_date,
    fixed_concept,
    section_with_extras,
    urn_uuid,
)
from app.fhir.constants import (
    CATEGORY_SOCIAL_HISTORY,
    LOINC_TOBACCO_SMOKING_STATUS,
    PROFILE_TOBACCO_USE,
    SECTION_SOCIAL_HISTORY,
    SMOKING_STATUS_VALUES,
)
from app.fhir.models import CodeableConcept, Meta, Observation
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import Enriched, SocialHistoryItem, SocialHistoryKind, TobaccoStatus

KEY = "social_history"
TITLE = "Social History"


def map_social_history(
    items: list[Enriched[SocialHistoryItem]], ctx: MappingContext
) -> SectionResult | None:
    if not items:
        return None
    entries: list[MappedResource] = []
    extra: list[NarrativeLine] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(items):
        path = f"{KEY}[{index}]"
        if item.extracted.kind is SocialHistoryKind.TOBACCO:
            entry, item_notes = _tobacco(item, path, ctx)
            entries.append(entry)
            notes += item_notes
            continue
        s = item.extracted
        extra.append(NarrativeLine("Alcohol use", (("as written", s.use_text),)))
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.NOT_REPRESENTABLE_IN_IPS,
                message="The IPS alcohol-use profile is a quantity (drinks per day); this fact "
                "is kept in the section narrative only.",
                severity="info",
            )
        )
    section = section_with_extras(SECTION_SOCIAL_HISTORY, TITLE, entries, extra)
    return SectionResult(section, KEY, entries, notes)


def _tobacco(
    item: Enriched[SocialHistoryItem], path: str, ctx: MappingContext
) -> tuple[MappedResource, list[MappingNote]]:
    s = item.extracted
    if s.tobacco_status is not TobaccoStatus.NOT_STATED:
        value = fixed_concept(SMOKING_STATUS_VALUES[s.tobacco_status.value], s.use_text)
    else:
        value = CodeableConcept(text=s.use_text)
    details: list[tuple[str, str]] = [("as written", s.use_text)]
    if s.tobacco_status is not TobaccoStatus.NOT_STATED:
        details.insert(0, ("status", s.tobacco_status.value))
    effective = effective_date(s.date, ctx)
    if effective.value:
        details.append(effective.detail())
    line = NarrativeLine("Tobacco use", tuple(details))
    resource = Observation(
        id=str(item.id),
        meta=Meta(profile=[PROFILE_TOBACCO_USE]),
        text=line_narrative(line),
        status="final",
        category=[fixed_concept(CATEGORY_SOCIAL_HISTORY)],
        code=fixed_concept(LOINC_TOBACCO_SMOKING_STATUS),
        subject=ctx.patient,
        effective_date_time=effective.value,
        primitive_extensions=None if effective.value else {"effectiveDateTime": data_absent()},
        value_codeable_concept=value,
        note=effective.annotations(None),
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), effective.notes(path)
