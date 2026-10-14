"""Problem List (required) and History of Past Illness (optional) sections -> Condition-uv-ips.

Routing (D-8), on the clinical status *as encoded*:

* ``resolved`` / ``inactive`` / ``remission`` -> History of Past Illness (LOINC 11348-0);
* ``active`` / ``recurrence`` / ``relapse`` / **``not_stated``** -> Problem List. A condition
  listed without a status stays visible as a current problem: wrongly hiding an active problem
  in the history is the more harmful error, and the reviewer can still move it.
* Exception: ``not_stated`` with an abatement date ("date resolved") is encoded as
  ``resolved`` (R4 con-4 requires an inactive/resolved/remission status when abatement is
  present) and therefore goes to the history, with a warning. An abatement date next to an
  active/recurrence/relapse status contradicts it (con-4): the date is not encoded (narrative
  only) and a warning is recorded.

The past-illness section is emitted only when it has entries. If every condition is past, the
Problem List has no entries and gets ``emptyReason`` ``unavailable`` (not the "no current
problems" code: the document did not state that) and a warning.

Variants: ``none_known`` -> one Condition coded 160245001 "No current problems or disability";
``no_information`` -> ``emptyReason`` ``unavailable``.

Item mapping: ``code`` = condition text + lookup codings (ICD-10 / SNOMED CT from the
terminology step only; a printed code such as "M54.5" becomes a coding only when that step
confirms it, which for FI/SV text needs ``TERMINOLOGY_MODE=llm``, D-9); ``category``
``problem-list-item`` on Problem List entries (not on past illness); verification status only
when stated; ``severity`` = the stated level as text plus lookup codings; ``bodySite`` text +
codings; ``onsetDateTime`` / ``abatementDateTime`` = partial dates; ``note``.

Clinical status: as stated. A Problem List entry without a stated status is encoded ``active``
with a warning (the reviewer confirms it), as for allergies: the Problem List is the list of
current problems, and consumers filter on ``clinicalStatus``. (R4 invariant con-3 asks for a
clinical status on a problem-list-item; Matchbox does not report it either way.)
"""

from __future__ import annotations

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
    CONDITION_CATEGORY_PROBLEM_LIST_ITEM,
    CONDITION_CLINICAL_STATUS,
    CONDITION_VERIFICATION_STATUS,
    NO_CURRENT_PROBLEMS,
    PROFILE_CONDITION,
    SECTION_PAST_PROBLEMS,
    SECTION_PROBLEMS,
)
from app.fhir.models import Annotation, Condition, Meta, Reference
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import (
    ConditionClinicalStatus,
    ConditionItem,
    ConditionVerificationStatus,
    Enriched,
    EnrichedProblemSection,
    ItemsFound,
    NoneKnown,
    Severity,
)

KEY = "problems"
PAST_KEY = "past_illness"
TITLE = "Problem List"
PAST_TITLE = "History of Past Illness"

PAST_STATUSES = frozenset(
    {
        ConditionClinicalStatus.RESOLVED,
        ConditionClinicalStatus.INACTIVE,
        ConditionClinicalStatus.REMISSION,
    }
)
_CURRENT_STATUSES = frozenset(
    {
        ConditionClinicalStatus.ACTIVE,
        ConditionClinicalStatus.RECURRENCE,
        ConditionClinicalStatus.RELAPSE,
    }
)


def map_problem_sections(
    section: EnrichedProblemSection, ctx: MappingContext
) -> list[SectionResult]:
    """Problem List always; History of Past Illness only when a condition is routed there."""
    if isinstance(section, NoneKnown):
        entry = _known_absent(ctx.new_id(f"{KEY}.none_known"), ctx.patient)
        return [SectionResult(entries_section(SECTION_PROBLEMS, TITLE, [entry]), KEY, [entry])]
    if not isinstance(section, ItemsFound):
        return [SectionResult(empty_section(SECTION_PROBLEMS, TITLE), KEY)]

    current: list[MappedResource] = []
    past: list[MappedResource] = []
    notes: list[MappingNote] = []
    for index, item in enumerate(section.items):
        entry, is_past, item_notes = map_condition(
            item, path=f"{KEY}.items[{index}]", patient=ctx.patient
        )
        (past if is_past else current).append(entry)
        notes += item_notes

    if current:
        problems = SectionResult(entries_section(SECTION_PROBLEMS, TITLE, current), KEY, current)
    else:
        problems = SectionResult(
            empty_section(
                SECTION_PROBLEMS,
                TITLE,
                narrative="No current problems documented; see History of Past Illness.",
            ),
            KEY,
        )
        notes.append(
            MappingNote(
                path=KEY,
                code=NoteCode.PROBLEM_LIST_ONLY_PAST,
                message="All conditions are past; Problem List emitted with emptyReason "
                "'unavailable'.",
            )
        )
    problems.notes = notes
    results = [problems]
    if past:
        results.append(
            SectionResult(entries_section(SECTION_PAST_PROBLEMS, PAST_TITLE, past), PAST_KEY, past)
        )
    return results


def _known_absent(resource_id: UUID, patient: Reference) -> MappedResource:
    line = NarrativeLine(NO_CURRENT_PROBLEMS.display)
    resource = Condition(
        id=str(resource_id),
        meta=Meta(profile=[PROFILE_CONDITION]),
        text=line_narrative(line),
        clinical_status=fixed_concept(CONDITION_CLINICAL_STATUS["active"]),
        code=fixed_concept(NO_CURRENT_PROBLEMS),
        subject=patient,
    )
    return MappedResource(KEY, None, urn_uuid(resource_id), resource, line)


def encoded_status(item: ConditionItem) -> ConditionClinicalStatus:
    """Clinical status as encoded (see module docstring for the abatement rule)."""
    if item.abatement and item.clinical_status is ConditionClinicalStatus.NOT_STATED:
        return ConditionClinicalStatus.RESOLVED
    return item.clinical_status


def is_past(item: ConditionItem) -> bool:
    """D-8: does the condition belong in History of Past Illness?"""
    return encoded_status(item) in PAST_STATUSES


def map_condition(
    item: Enriched[ConditionItem], *, path: str, patient: Reference
) -> tuple[MappedResource, bool, list[MappingNote]]:
    """Return the Condition, whether it is past (D-8), and mapping notes."""
    c = item.extracted
    notes = printed_code_note(path, c.printed_code)
    status = encoded_status(c)
    abatement = c.abatement
    details: list[tuple[str, str]] = []

    if status is not c.clinical_status:
        details.append(("status", f"{status.value} (inferred from resolution date)"))
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.CONDITION_STATUS_INFERRED_FROM_ABATEMENT,
                message="Clinical status not stated but a resolution date is; encoded as "
                "'resolved' (con-4).",
            )
        )
    elif status is not ConditionClinicalStatus.NOT_STATED:
        details.append(("status", status.value))
    past = status in PAST_STATUSES
    if status is ConditionClinicalStatus.NOT_STATED:
        status = ConditionClinicalStatus.ACTIVE
        details.append(("status", "active (not stated; assumed for the Problem List)"))
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.CONDITION_STATUS_ASSUMED_ACTIVE,
                message="Clinical status not stated; encoded as 'active' because the condition "
                "is on the Problem List. Confirm it in review.",
            )
        )
    if abatement and status in _CURRENT_STATUSES:
        notes.append(
            MappingNote(
                path=path,
                code=NoteCode.ABATEMENT_CONFLICTS_WITH_STATUS,
                message="Resolution date contradicts a current clinical status; date not "
                "encoded (narrative only).",
            )
        )
        details.append(("resolution date (not encoded, conflicts with status)", abatement))
        abatement = None

    verification = None
    if c.verification_status is not ConditionVerificationStatus.NOT_STATED:
        verification = fixed_concept(CONDITION_VERIFICATION_STATUS[c.verification_status.value])
        details.append(("verification", c.verification_status.value))
    severity = None
    if c.severity is not Severity.NOT_STATED:
        severity = concept(c.severity.value, item.codings_for("severity"))
        details.append(("severity", c.severity.value))
    if c.body_site_text:
        details.append(("body site", c.body_site_text))
    if c.onset:
        details.append(("onset", c.onset))
    if abatement:
        details.append(("resolved", abatement))
    if c.note:
        details.append(("note", c.note))

    body_site = concept(c.body_site_text, item.codings_for("body_site_text"))
    line = NarrativeLine(c.condition_text, tuple(details))
    resource = Condition(
        id=str(item.id),
        meta=Meta(profile=[PROFILE_CONDITION]),
        text=line_narrative(line),
        clinical_status=fixed_concept(CONDITION_CLINICAL_STATUS[status.value]),
        verification_status=verification,
        category=None if past else [fixed_concept(CONDITION_CATEGORY_PROBLEM_LIST_ITEM)],
        severity=severity,
        code=concept(c.condition_text, item.codings_for("condition_text")),
        body_site=[body_site] if body_site else None,
        subject=patient,
        onset_date_time=c.onset,
        abatement_date_time=abatement,
        note=[Annotation(text=c.note)] if c.note else None,
    )
    entry = MappedResource(path, item.id, urn_uuid(item.id), resource, line)
    return entry, past, notes
