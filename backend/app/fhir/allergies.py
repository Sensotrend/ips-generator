"""Allergies and Intolerances section (required) -> AllergyIntolerance-uv-ips.

Section variants (D7):

* ``items_found``: one AllergyIntolerance per item. Scoped "no known ..." statements next to
  the items (D-7) become an extra AllergyIntolerance with the IPS-allowed SNOMED CT code for the
  scope (descendants of 716186003, see ``constants``): medication -> 409137002, food ->
  429625007, environment -> 428607008 (the IG example Bundle-01 does the same for food).
  A statement is **not coded** when it contradicts a listed item: scope ``all`` (an allergy is
  listed) or a scope matching a listed item's category (e.g. "NKDA" next to a penicillin
  allergy). It is then kept in the section narrative only, with a warning. Statements of the
  same scope share one resource.
* ``none_known``: one AllergyIntolerance coded for the statement's scope (``all`` ->
  716186003 "No known allergy").
* ``no_information``: no entries, ``emptyReason`` = ``unavailable``.

Item mapping: ``code`` = substance text + lookup codings; ``type``/``category``/
``criticality``/``verificationStatus`` only when stated; ``onsetDateTime`` = the partial date;
reactions with their manifestations (text + lookup codings) and severity.
``clinicalStatus``: R4 invariant ait-1 makes it mandatory (unless entered-in-error) and its
required binding rejects a data-absent-reason, so a *not stated* status becomes ``active`` (an
allergy listed in a summary is presumed current) with a warning for the reviewer.
Known-absent resources carry ``clinicalStatus`` ``active`` only, as in the IG examples.
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
    empty_section,
    entries_section,
    fixed_concept,
    printed_code_note,
    urn_uuid,
)
from app.fhir.constants import (
    ALLERGY_CLINICAL_STATUS,
    ALLERGY_VERIFICATION_STATUS,
    NO_KNOWN_ALLERGY,
    NO_KNOWN_DRUG_ALLERGY,
    NO_KNOWN_ENVIRONMENTAL_ALLERGY,
    NO_KNOWN_FOOD_ALLERGY,
    PROFILE_ALLERGY_INTOLERANCE,
    SECTION_ALLERGIES,
    FixedCode,
)
from app.fhir.models import (
    AllergyIntolerance,
    AllergyIntoleranceReaction,
    Annotation,
    CodeableConcept,
    Meta,
    Reference,
)
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import (
    AllergiesFound,
    AllergyCategory,
    AllergyClinicalStatus,
    AllergyCriticality,
    AllergyItem,
    AllergyScope,
    AllergyType,
    AllergyVerificationStatus,
    Enriched,
    EnrichedAllergySection,
    NoKnownAllergies,
    Severity,
)

KEY = "allergies"
TITLE = "Allergies and Intolerances"

SCOPE_CODES: dict[AllergyScope, FixedCode] = {
    AllergyScope.ALL: NO_KNOWN_ALLERGY,
    AllergyScope.MEDICATION: NO_KNOWN_DRUG_ALLERGY,
    AllergyScope.FOOD: NO_KNOWN_FOOD_ALLERGY,
    AllergyScope.ENVIRONMENT: NO_KNOWN_ENVIRONMENTAL_ALLERGY,
}
_TYPE: dict[AllergyType, Literal["allergy", "intolerance"]] = {
    AllergyType.ALLERGY: "allergy",
    AllergyType.INTOLERANCE: "intolerance",
}
_CATEGORY: dict[AllergyCategory, Literal["food", "medication", "environment", "biologic"]] = {
    AllergyCategory.FOOD: "food",
    AllergyCategory.MEDICATION: "medication",
    AllergyCategory.ENVIRONMENT: "environment",
    AllergyCategory.BIOLOGIC: "biologic",
}
_CRITICALITY: dict[AllergyCriticality, Literal["low", "high", "unable-to-assess"]] = {
    AllergyCriticality.LOW: "low",
    AllergyCriticality.HIGH: "high",
    AllergyCriticality.UNABLE_TO_ASSESS: "unable-to-assess",
}
_SEVERITY: dict[Severity, Literal["mild", "moderate", "severe"]] = {
    Severity.MILD: "mild",
    Severity.MODERATE: "moderate",
    Severity.SEVERE: "severe",
}
_SCOPE_CATEGORY: dict[AllergyScope, AllergyCategory] = {
    AllergyScope.MEDICATION: AllergyCategory.MEDICATION,
    AllergyScope.FOOD: AllergyCategory.FOOD,
    AllergyScope.ENVIRONMENT: AllergyCategory.ENVIRONMENT,
}


def map_allergy_section(section: EnrichedAllergySection, ctx: MappingContext) -> SectionResult:
    if isinstance(section, NoKnownAllergies):
        code = SCOPE_CODES[section.scope]
        entry = _known_absent(code, ctx.new_id(f"{KEY}.none_known"), ctx.patient, KEY)
        return SectionResult(entries_section(SECTION_ALLERGIES, TITLE, [entry]), KEY, [entry])
    if isinstance(section, AllergiesFound):
        return _items_found(section, ctx)
    return SectionResult(empty_section(SECTION_ALLERGIES, TITLE), KEY)


def _items_found(
    section: AllergiesFound[Enriched[AllergyItem]], ctx: MappingContext
) -> SectionResult:
    entries: list[MappedResource] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(section.items):
        entry, item_notes = map_allergy(item, path=f"{KEY}.items[{index}]", patient=ctx.patient)
        entries.append(entry)
        notes += item_notes

    listed = {item.extracted.category for item in section.items}
    by_scope: dict[AllergyScope, MappedResource] = {}
    uncoded: list[NarrativeLine] = []
    for index, statement in enumerate(section.none_known_statements):
        path = f"{KEY}.none_known_statements[{index}]"
        scope = statement.scope
        code = SCOPE_CODES[scope]
        if scope is AllergyScope.ALL or _SCOPE_CATEGORY[scope] in listed:
            uncoded.append(
                NarrativeLine(
                    code.display,
                    (("note", "stated in the source; not coded, conflicts with listed entries"),),
                )
            )
            notes.append(
                MappingNote(
                    path=path,
                    code=NoteCode.SCOPED_STATEMENT_NOT_CODED,
                    message=f"'No known' statement (scope {scope.value}) contradicts a listed "
                    "allergy; kept in the section narrative only (D-7).",
                )
            )
            continue
        shared = by_scope.get(scope)
        if shared is None:
            resource_id = ctx.new_id(f"{KEY}.none_known.{scope.value}")
            shared = by_scope[scope] = _known_absent(code, resource_id, ctx.patient, path)
            entries.append(shared)
        else:
            entries.append(
                MappedResource(path, None, shared.full_url, shared.resource, shared.narrative)
            )

    section_out = entries_section(SECTION_ALLERGIES, TITLE, entries, extra_lines=uncoded)
    return SectionResult(section_out, KEY, entries, notes)


def _known_absent(
    code: FixedCode, resource_id: UUID, patient: Reference, path: str
) -> MappedResource:
    line = NarrativeLine(code.display)
    resource = AllergyIntolerance(
        id=str(resource_id),
        meta=Meta(profile=[PROFILE_ALLERGY_INTOLERANCE]),
        text=line_narrative(line),
        clinical_status=fixed_concept(ALLERGY_CLINICAL_STATUS["active"]),
        code=fixed_concept(code),
        patient=patient,
    )
    return MappedResource(path, None, urn_uuid(resource_id), resource, line)


def map_allergy(
    item: Enriched[AllergyItem], *, path: str, patient: Reference
) -> tuple[MappedResource, list[MappingNote]]:
    a = item.extracted
    notes = printed_code_note(path, a.printed_code)
    details: list[tuple[str, str]] = []

    if a.clinical_status is AllergyClinicalStatus.NOT_STATED:
        clinical = "active"
        details.append(("status", "active (assumed; not stated)"))
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.ALLERGY_CLINICAL_STATUS_DEFAULTED,
                message="Clinical status not stated; set to 'active' because FHIR R4 (ait-1) "
                "requires it.",
            )
        )
    else:
        clinical = a.clinical_status.value
        details.append(("status", clinical))
    verification = None
    if a.verification_status is not AllergyVerificationStatus.NOT_STATED:
        verification = fixed_concept(ALLERGY_VERIFICATION_STATUS[a.verification_status.value])
        details.append(("verification", a.verification_status.value))

    allergy_type = _TYPE.get(a.type)
    category = _CATEGORY.get(a.category)
    criticality = _CRITICALITY.get(a.criticality)
    details += [
        (label, value)
        for label, value in (
            ("type", allergy_type),
            ("category", category),
            ("criticality", criticality),
            ("onset", a.onset),
        )
        if value is not None
    ]

    reactions: list[AllergyIntoleranceReaction] = []
    for r_index, reaction in enumerate(a.reactions):
        manifestations: list[CodeableConcept] = []
        for m_index, text in enumerate(reaction.manifestations):
            mpath = f"reactions[{r_index}].manifestations[{m_index}]"
            manifestation = concept(text, item.codings_for(mpath))
            if manifestation is not None:
                manifestations.append(manifestation)
        severity = _SEVERITY.get(reaction.severity)
        if not manifestations:  # R4: manifestation 1..*
            notes.append(
                MappingNote(
                    path=f"{path}.reactions[{r_index}]",
                    code=NoteCode.REACTION_WITHOUT_MANIFESTATION,
                    message="Reaction without a manifestation cannot be encoded; omitted.",
                )
            )
            continue
        reactions.append(
            AllergyIntoleranceReaction(manifestation=manifestations, severity=severity)
        )
        reaction_text = ", ".join(reaction.manifestations)
        details.append(("reaction", f"{reaction_text} ({severity})" if severity else reaction_text))
    if a.note:
        details.append(("note", a.note))

    line = NarrativeLine(a.substance_text, tuple(details))
    resource = AllergyIntolerance(
        id=str(item.id),
        meta=Meta(profile=[PROFILE_ALLERGY_INTOLERANCE]),
        text=line_narrative(line),
        clinical_status=fixed_concept(ALLERGY_CLINICAL_STATUS[clinical]),
        verification_status=verification,
        type=allergy_type,
        category=[category] if category else None,
        criticality=criticality,
        code=concept(a.substance_text, item.codings_for("substance_text")),
        patient=patient,
        onset_date_time=a.onset,
        note=[Annotation(text=a.note)] if a.note else None,
        reaction=reactions or None,
    )
    return MappedResource(path, item.id, urn_uuid(item.id), resource, line), notes
