"""Shared building blocks of the section mappers: mapping records, codings, references, sections.

Mappers are pure functions of the enriched intermediate data (``EnrichedIps``): no I/O, no
logging, no LLM. Codes come only from (a) the enriched items' ``TerminologyCoding``s
(terminology-server lookups) or (b) the IG/FHIR-fixed constants in ``app.fhir.constants``
(D-1, D-2). ``printed_code`` (D-9) is never turned into a coding.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.fhir.constants import (
    DATA_ABSENT_REASON_URL,
    DATA_ABSENT_UNKNOWN,
    EMPTY_REASON_UNAVAILABLE,
    FixedCode,
)
from app.fhir.models import (
    AllergyIntolerance,
    Annotation,
    CodeableConcept,
    Coding,
    Composition,
    CompositionSection,
    Condition,
    Device,
    DeviceUseStatement,
    Extension,
    Immunization,
    MedicationStatement,
    Observation,
    Patient,
    PrimitiveElement,
    Procedure,
    Reference,
)
from app.fhir.narrative import NarrativeLine, list_narrative, text_narrative
from app.schemas.intermediate import TerminologyCoding

IdFactory = Callable[[str], UUID]
"""Returns the UUID for a resource without a stable item id, keyed by a role such as
``"patient"`` or ``"medications.none_known"``. Must be deterministic for reproducible Bundles."""

MappedFhirResource = (
    AllergyIntolerance
    | Composition
    | Condition
    | Device
    | DeviceUseStatement
    | Immunization
    | MedicationStatement
    | Observation
    | Patient
    | Procedure
)
"""Resource types the mappers produce."""

NO_INFORMATION_TEXT = "No information available"


class NoteCode(StrEnum):
    """Why a mapping note was raised. Notes never contain document content."""

    BIRTH_DATE_MISSING = "birth_date_missing"  # _birthDate with data-absent-reason
    BIRTH_DATE_DERIVED = "birth_date_derived"  # D-10: from a Finnish personal identity code
    GENDER_DERIVED = "gender_derived"  # D-10: from a Finnish personal identity code
    PATIENT_NAME_MISSING = "patient_name_missing"  # name._text with data-absent-reason
    PRINTED_CODE_NOT_EMITTED = "printed_code_not_emitted"  # D-9: text hint only
    CODING_NOT_EMITTED = "coding_not_emitted"  # a lookup coding with no FHIR element to go to
    SCOPED_STATEMENT_NOT_CODED = "scoped_statement_not_coded"  # D-7: kept as narrative only
    ALLERGY_CLINICAL_STATUS_DEFAULTED = "allergy_clinical_status_defaulted"  # ait-1
    REACTION_WITHOUT_MANIFESTATION = "reaction_without_manifestation"
    CONDITION_STATUS_INFERRED_FROM_ABATEMENT = "condition_status_inferred_from_abatement"
    ABATEMENT_CONFLICTS_WITH_STATUS = "abatement_conflicts_with_status"  # con-4
    PROBLEM_LIST_ONLY_PAST = "problem_list_only_past"  # all conditions routed to past illness
    MEDICATION_EFFECTIVE_UNKNOWN = "medication_effective_unknown"
    MEDICATION_PERIOD_INVERTED = "medication_period_inverted"  # per-1
    DOSAGE_TIMING_INCOMPLETE = "dosage_timing_incomplete"
    SECTION_UNVERIFIED = "section_unverified"  # grounding turned the section to no_information
    VITAL_SIGN_UNIT_UNRECOGNISED = "vital_sign_unit_unrecognised"  # D-14: kept as text, no Quantity
    VITAL_SIGN_DIASTOLIC_MISSING = "vital_sign_diastolic_missing"
    VITAL_SIGN_NOT_DATED = "vital_sign_not_dated"  # no day-precise date: narrative only
    PREGNANCY_FACT_INCOMPLETE = "pregnancy_fact_incomplete"  # no status/date/count: not emitted
    NOT_REPRESENTABLE_IN_IPS = "not_representable_in_ips"  # kept in the section narrative only
    IMMUNIZATION_NOT_CODED = "immunization_not_coded"  # vaccine not in the D-14 table: text only
    EFFECTIVE_IS_DOCUMENT_DATE = "effective_is_document_date"  # D-15: stand-in effective date
    CONDITION_STATUS_ASSUMED_ACTIVE = "condition_status_assumed_active"  # Problem List, not stated
    RESULT_WITHOUT_VALUE = "result_without_value"  # no number or text: data-absent-reason
    RESULT_UNIT_NOT_CODED = "result_unit_not_coded"  # unit kept as text, no UCUM code (info)
    PROCEDURE_NOT_DATED = "procedure_not_dated"  # performed[x] is "Date not stated" (info)


@dataclass(frozen=True, slots=True)
class MappingNote:
    """Something the reviewer should know about how a fact was mapped (no PHI in ``message``)."""

    path: str
    """Path in ``EnrichedIps`` (same convention as ``ground.py``), e.g. ``allergies.items[0]``."""
    code: NoteCode
    message: str
    severity: Literal["info", "warning"] = "warning"


@dataclass(frozen=True, slots=True)
class MappedResource:
    """A resource produced from one fact (or one IG-fixed statement) of ``EnrichedIps``."""

    path: str
    """Source path in ``EnrichedIps`` (``patient`` for the Patient, ``""`` for pipeline-made
    resources such as the author Device)."""
    item_id: UUID | None
    """Stable id of the enriched item, when the source is an ``Enriched[...]`` item."""
    full_url: str
    resource: MappedFhirResource
    narrative: NarrativeLine | None = None
    """The fact as rendered in its section narrative (``None`` for non-section resources)."""


@dataclass(frozen=True, slots=True)
class MappingContext:
    """What every section mapper needs besides its section."""

    patient: Reference
    new_id: IdFactory
    document_date: str | None = None
    """The document's own date when it is precise to the day (YYYY-MM-DD), else ``None``: the
    stand-in ``effective[x]`` of an Observation without a stated date (PLAN.md D-15)."""


@dataclass(slots=True)
class SectionResult:
    section: CompositionSection
    key: str
    """Section key used in mapping records: ``allergies``, ``medications``, ``problems``,
    ``past_illness``, ``immunizations``, ``results``, ``procedures``, ``devices``,
    ``pregnancy``, ``social_history``, ``vital_signs``."""
    entries: list[MappedResource] = field(default_factory=list)
    notes: list[MappingNote] = field(default_factory=list)


def urn_uuid(value: UUID) -> str:
    return f"urn:uuid:{value}"


def reference(full_url: str) -> Reference:
    return Reference(reference=full_url)


def lookup_coding(coding: TerminologyCoding) -> Coding:
    """A FHIR ``Coding`` from a terminology-server result (the only source of clinical codes)."""
    return Coding(
        system=coding.system, version=coding.version, code=coding.code, display=coding.display
    )


def fixed_coding(code: FixedCode) -> Coding:
    return Coding(system=code.system, code=code.code, display=code.display)


def concept(text: str | None, codings: Sequence[TerminologyCoding] = ()) -> CodeableConcept | None:
    """Text plus lookup codings; ``None`` when there is neither."""
    if text is None and not codings:
        return None
    return CodeableConcept(coding=[lookup_coding(c) for c in codings] or None, text=text)


def fixed_concept(code: FixedCode, text: str | None = None) -> CodeableConcept:
    return CodeableConcept(coding=[fixed_coding(code)], text=text)


def data_absent(reason: str = DATA_ABSENT_UNKNOWN) -> PrimitiveElement:
    """``_element`` companion carrying a data-absent-reason extension (no value)."""
    return PrimitiveElement(extension=[Extension(url=DATA_ABSENT_REASON_URL, value_code=reason)])


def entries_section(
    code: FixedCode,
    title: str,
    entries: Sequence[MappedResource],
    *,
    extra_lines: Sequence[NarrativeLine] = (),
) -> CompositionSection:
    """A section listing ``entries`` (de-duplicated by fullUrl) with a narrative of their lines.

    ``extra_lines`` adds facts kept as narrative only (e.g. an uncoded scoped statement)."""
    seen: dict[str, NarrativeLine | None] = {}
    for entry in entries:
        seen.setdefault(entry.full_url, entry.narrative)
    lines = [line for line in seen.values() if line is not None] + list(extra_lines)
    return CompositionSection(
        title=title,
        code=fixed_concept(code),
        text=list_narrative(lines),
        entry=[reference(url) for url in seen],
    )


def empty_section(
    code: FixedCode, title: str, *, narrative: str = NO_INFORMATION_TEXT
) -> CompositionSection:
    """A section without entries; ``emptyReason`` list-empty-reason ``unavailable`` (ips-comp-1)."""
    return CompositionSection(
        title=title,
        code=fixed_concept(code),
        text=text_narrative(narrative),
        empty_reason=fixed_concept(EMPTY_REASON_UNAVAILABLE, text=NO_INFORMATION_TEXT),
    )


def section_with_extras(
    code: FixedCode,
    title: str,
    entries: Sequence[MappedResource],
    extra_lines: Sequence[NarrativeLine],
) -> CompositionSection:
    """A section of ``entries`` plus facts kept as narrative only (``extra_lines``). With no
    entries the section has just that narrative and ``emptyReason`` ``unavailable`` (ips-comp-1)."""
    if entries:
        return entries_section(code, title, entries, extra_lines=extra_lines)
    section = empty_section(code, title)
    section.text = list_narrative(list(extra_lines))
    return section


def printed_code_note(path: str, printed_code: str | None) -> list[MappingNote]:
    """D-9: a printed code is a text hint for the terminology step, never a FHIR coding."""
    if printed_code is None:
        return []
    return [
        MappingNote(
            path=path,
            code=NoteCode.PRINTED_CODE_NOT_EMITTED,
            message="Printed code kept as a hint only; not emitted as a coding or narrative (D-9).",
            severity="info",
        )
    ]


STAND_IN_DATE_NOTE = (
    "The document does not state when this was recorded; the effective date is the date of the "
    "document."
)
"""``Observation.note`` text that marks a stand-in effective date (D-15). FHIR has no standard
element for "this date is approximate", so the marker is this note, the narrative and the
``effective_is_document_date`` mapping note."""


@dataclass(frozen=True, slots=True)
class Effective:
    """``effectiveDateTime`` of an Observation: a stated date, the stand-in document date, or
    nothing (then the mapper uses a data-absent-reason or keeps the fact narrative-only)."""

    value: str | None
    stand_in: bool = False

    def detail(self) -> tuple[str, str]:
        """The narrative ``date`` detail."""
        if self.value is None:
            return ("date", "not stated")
        if self.stand_in:
            return ("date", f"not stated; document date {self.value} used")
        return ("date", self.value)

    def annotations(self, note: str | None) -> list[Annotation] | None:
        """``Observation.note``: the item's note, plus the stand-in marker when it applies."""
        texts = [t for t in (note, STAND_IN_DATE_NOTE if self.stand_in else None) if t]
        return [Annotation(text=t) for t in texts] or None

    def notes(self, path: str) -> list[MappingNote]:
        if not self.stand_in:
            return []
        return [
            MappingNote(
                path=path,
                code=NoteCode.EFFECTIVE_IS_DOCUMENT_DATE,
                message="No date stated for this fact; the document date is used as its "
                "effective date (D-15). Check it in review.",
            )
        ]


def effective_date(
    stated: str | None, ctx: MappingContext, *, day_precise: bool = False
) -> Effective:
    """The stated date if it is usable, else the document date as a stand-in (D-15).

    ``day_precise``: the profile needs a full date (vital signs, vs-1). A stated year or month is
    then not usable, and the document date is not used instead either: it would contradict the
    stated date. The result is then empty (the fact stays narrative-only)."""
    if stated is not None:
        if not day_precise or len(stated) >= 10:
            return Effective(stated)
        return Effective(None)
    if ctx.document_date is not None:
        return Effective(ctx.document_date, stand_in=True)
    return Effective(None)
