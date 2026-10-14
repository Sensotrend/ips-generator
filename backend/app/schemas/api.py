"""API request and response schemas (PLAN Phase 3).

Error responses never contain document content: ``ErrorBody.message`` is a fixed string or an
ingest/pipeline message that is PHI-free by contract. Draft and source responses *do* contain
patient data; they are sent only to the authenticated reviewer and must never be cached
(``Cache-Control: no-store``; the PWA service worker routes ``/api/`` NetworkOnly).
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.pipeline.run import ValidationSummary

# ---- errors ---------------------------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)
    """Structured, PHI-free details (paths, codes, counts)."""


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---- jobs -----------------------------------------------------------------------------------


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW = "review"  # draft ready for review
    APPROVED = "approved"
    FAILED = "failed"


class JobError(BaseModel):
    step: str | None
    code: str
    message: str


class JobOut(BaseModel):
    id: UUID
    status: JobStatus
    created_at: dt.datetime
    updated_at: dt.datetime
    media_type: str
    size_bytes: int
    extractor: str
    current_step: str | None
    error: JobError | None
    draft_version: int | None
    approved_at: dt.datetime | None


class JobEventOut(BaseModel):
    """One SSE ``data:`` payload. ``step`` is a pipeline step or ``job`` (lifecycle)."""

    seq: int
    step: str
    status: str
    detail: dict[str, int | str | bool] = Field(default_factory=dict)
    at: dt.datetime


TERMINAL_JOB_EVENTS = frozenset({"review_ready", "failed", "approved"})
"""``job`` event statuses after which the progress stream ends."""


# ---- source -----------------------------------------------------------------------------------


class SegmentOut(BaseModel):
    page: int
    locator: str | None
    text: str


class SourceOut(BaseModel):
    media_type: str
    page_count: int
    pages_without_text: list[int]
    segments: list[SegmentOut]
    original_url: str | None
    """Download URL of the original file (PDF only: the viewer renders it with pdf.js)."""
    json_text: str | None = None
    """JSON documents only: the document re-serialised, for the viewer's raw-JSON mode."""


# ---- draft ----------------------------------------------------------------------------------


class Decision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class FlagCode(StrEnum):
    """Review flags shown in the UI (grounding, derivation, mapping, review state)."""

    RELOCATED = "relocated"
    FUZZY_MATCH = "fuzzy_match"
    SECTION_UNVERIFIED = "section_unverified"
    PRINTED_CODE_NOT_IN_QUOTE = "printed_code_not_in_quote"
    DERIVED_FROM_IDENTITY_CODE = "derived_from_identity_code"
    IDENTITY_CODE_CONFLICT = "identity_code_conflict"
    IDENTITY_CODE_AMBIGUOUS = "identity_code_ambiguous"
    ASSUMED_STATUS = "assumed_status"
    """Allergy clinicalStatus not stated; assembled as ``active`` until the reviewer confirms."""
    LOW_CONFIDENCE = "low_confidence"
    EDITED = "edited"
    OTHER = "other"


class SourceRef(BaseModel):
    quote: str
    page: int
    locator: str | None


class NoteOut(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning"]


FactKind = Literal[
    "patient_name",
    "patient_identifier",
    "patient_birth_date",
    "patient_gender",
    "document_date",
    "allergy",
    "medication",
    "condition",
    "vital_sign",
    "social_history",
    "immunization",
    "pregnancy_fact",
    "patient_contact",
    "no_known_allergy_statement",
    "section_none_known",
]


class FactOut(BaseModel):
    """One reviewable fact: an item, a "none known" statement or a patient fact."""

    path: str
    """Stable within a draft: ``allergies.items[0]``, ``allergies.none_known_statements[0]``,
    ``medications`` (section statement), ``patient.names[0]``, ``patient.birth_date``."""
    item_id: UUID | None
    kind: FactKind
    value: dict[str, Any]
    """The fact as in ``EnrichedIps`` (an item's ``extracted`` part), with reviewer edits."""
    pipeline_value: dict[str, Any] | None
    """The fact as the pipeline produced it, when the reviewer edited it."""
    source: SourceRef | None
    """Where the fact is quoted; ``None`` for a value derived from another fact."""
    derived: dict[str, Any] | None = None
    """Derivation details (D-10) for a derived patient value: ``{"value": ..., "derivation":
    {...}}``."""
    decision: Decision
    needs_confirmation: bool
    """Derived value (D-10) or assumed allergy status that the reviewer has not confirmed."""
    confirmed: bool
    flags: list[FlagCode]
    notes: list[NoteOut]
    codings: list[dict[str, Any]] = Field(default_factory=list)
    """Terminology codes for the item's text fields (from server lookups only)."""


SectionKey = Literal[
    "allergies",
    "medications",
    "problems",
    "past_illness",
    "immunizations",
    "pregnancy",
    "social_history",
    "vital_signs",
]


class SectionOut(BaseModel):
    key: SectionKey
    title: str
    kind: Literal["items_found", "none_known", "no_information"]
    """As produced by the pipeline (before reviewer rejections)."""
    effective_kind: Literal["items_found", "none_known", "no_information"]
    """What the Bundle will say after rejections are applied."""
    statement: FactOut | None
    """The section's own "none known" statement (``kind == none_known``)."""
    items: list[FactOut]
    scoped_statements: list[FactOut]
    """D-7: scoped "no known ..." statements next to allergy items."""
    flags: list[FlagCode]


class PatientOut(BaseModel):
    names: list[FactOut]
    identifiers: list[FactOut]
    contacts: list[FactOut] = Field(default_factory=list)
    birth_date: FactOut | None
    gender: FactOut | None
    flags: list[FlagCode]


class BlockerCode(StrEnum):
    PATIENT_NAME_MISSING = "patient_name_missing"
    PATIENT_BIRTH_DATE_MISSING = "patient_birth_date_missing"
    DERIVED_VALUE_UNCONFIRMED = "derived_value_unconfirmed"


class Blocker(BaseModel):
    code: BlockerCode
    path: str | None
    message: str


class DocumentInfoOut(BaseModel):
    """Metadata of the summary as a document: shown on screen and in the printout."""

    software: str
    software_version: str
    ai_assisted: bool
    """Always true: the extraction step is an LLM (also in the Bundle: Composition AIAST label)."""
    created_at: dt.datetime
    approved_at: dt.datetime | None
    attester_mode: Literal["personal", "professional"] | None
    """Who attested the approved summary: the patient or a clinician; ``None`` until approved."""


class DraftOut(BaseModel):
    job_id: UUID
    version: int
    status: JobStatus
    document_language: str
    document: DocumentInfoOut
    patient: PatientOut
    document_date: FactOut | None = None
    """The date the document states for itself (schema 1.3.0): the stand-in effective date of
    Observations without their own (PLAN.md D-15). Rejecting it removes the stand-in dates."""
    sections: list[SectionOut]
    notes: list[NoteOut]
    """Assembly notes of the current draft that belong to no single fact."""
    dropped_paths: list[str]
    """Facts removed by grounding (quote not found); paths only."""
    blockers: list[Blocker]
    """Why approval is not possible yet (D-4, D-10); empty when it is."""
    validation: ValidationSummary | None
    validation_error: str | None


# ---- review actions -------------------------------------------------------------------------


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class AcceptAction(_Action):
    action: Literal["accept"]


class RejectAction(_Action):
    action: Literal["reject"]


class ResetAction(_Action):
    """Undo: restore the pipeline value and set the fact back to pending."""

    action: Literal["reset"]


class EditAction(_Action):
    """Replace the fact's value. Provenance (``source_quote``, ``page``, ``locator``) must not
    change: a reviewer corrects what the quote says, never where it comes from."""

    action: Literal["edit"]
    value: dict[str, Any]


class ConfirmAction(_Action):
    """Confirm a derived patient value (D-10) or an allergy's clinical status (assumed
    ``active`` when not stated). ``clinical_status`` applies to allergy items only."""

    action: Literal["confirm"]
    clinical_status: Literal["active", "inactive", "resolved"] | None = None


ReviewAction = Annotated[
    AcceptAction | RejectAction | ResetAction | EditAction | ConfirmAction,
    Field(discriminator="action"),
]


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    """The draft version the actions were made against (optimistic concurrency)."""
    actions: list[ReviewAction] = Field(min_length=1, max_length=200)


# ---- approval -------------------------------------------------------------------------------


class ReviewerRole(StrEnum):
    PATIENT = "patient"
    CLINICIAN = "clinician"


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    role: ReviewerRole
    """``patient``: the reviewer is the patient (attester mode ``personal``); ``clinician``:
    attester mode ``professional`` (D-4)."""


class ApprovalOut(BaseModel):
    job_id: UUID
    approved_at: dt.datetime
    approved_by: str
    attester_mode: Literal["personal", "professional"]
    validation: ValidationSummary | None
    ips_url: str


class CurrentUserOut(BaseModel):
    id: str
    display_name: str
    auth_mode: str
