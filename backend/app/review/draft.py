"""Review drafts: stored state, reviewer actions and the approval blockers.

A draft keeps two copies of the enriched intermediate data:

* ``pipeline`` - what the pipeline produced (never changed), and
* ``current`` - the same with reviewer *edits* and confirmations applied.

Nothing is ever removed from ``current``: a rejection is a review decision stored in
``reviews``. Hence a fact's *path* (``allergies.items[2]``, ``patient.names[0]``,
``allergies.none_known_statements[0]``, ``medications`` for a section statement,
``patient.birth_date``) is stable for the lifetime of a draft and is the key for decisions,
grounding flags (whose paths refer to the grounded extraction, which has the same shape) and
derivation flags.

`effective_enriched` applies the rejections and gives what is assembled into the Bundle, plus a
map from its paths back to the draft paths (so assembly notes can be shown on the right fact).

Pure functions on Pydantic models: no I/O, no logging (drafts contain PHI).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.pipeline.ground import ReviewFlag
from app.pipeline.run import ValidationSummary, detect_derived_paths
from app.schemas.api import (
    Blocker,
    BlockerCode,
    ConfirmAction,
    Decision,
    EditAction,
    FactKind,
    RejectAction,
    ResetAction,
    ReviewAction,
)
from app.schemas.intermediate import (
    AllergyClinicalStatus,
    AllergyItem,
    Enriched,
    EnrichedIps,
    NoKnownAllergies,
    NoneKnown,
    resolve_path,
)

__all__ = [
    "SECTION_KEYS",
    "UNREVIEWED_SECTIONS",
    "DraftState",
    "Effective",
    "FactRef",
    "FactReview",
    "ReviewError",
    "apply_actions",
    "approval_blockers",
    "effective_enriched",
    "find_fact",
    "iter_facts",
    "map_back",
    "needs_confirmation",
    "new_draft",
]

# IPS section order: Problem List, Allergies and Intolerances, Medication Summary (History of
# Past Illness, a Problem List split-off, follows them).
SECTION_KEYS: Final = ("problems", "allergies", "medications")
UNREVIEWED_SECTIONS: Final = ("vital_signs", "social_history", "immunizations", "pregnancy")
"""Optional sections (schema 1.2.0) that exist in ``EnrichedIps`` but are not reviewable yet."""
_PROVENANCE_FIELDS: Final = ("source_quote", "page", "locator")
_PATH_PART: Final = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?$")


class ReviewError(ValueError):
    """A reviewer action cannot be applied. ``code`` and the message are PHI-free."""

    def __init__(self, code: str, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


class FactReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision = Decision.PENDING
    confirmed: bool = False
    by: str | None = None
    at: dt.datetime | None = None


class DraftState(BaseModel):
    """Stored per job (contains PHI: keep it in the database, never in logs)."""

    model_config = ConfigDict(extra="forbid")

    pipeline: EnrichedIps
    current: EnrichedIps
    reviews: dict[str, FactReview] = Field(default_factory=dict)
    flags: list[ReviewFlag] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    validation: ValidationSummary | None = None
    validation_error: str | None = None

    def review(self, path: str) -> FactReview:
        return self.reviews.get(path) or FactReview()

    def is_rejected(self, path: str) -> bool:
        return self.review(path).decision is Decision.REJECTED

    @property
    def derived_paths(self) -> tuple[str, ...]:
        return detect_derived_paths(self.current)


def new_draft(
    enriched: EnrichedIps,
    *,
    flags: tuple[ReviewFlag, ...] | list[ReviewFlag] = (),
    dropped: tuple[str, ...] | list[str] = (),
    validation: ValidationSummary | None = None,
    validation_error: str | None = None,
) -> DraftState:
    return DraftState(
        pipeline=enriched,
        current=enriched,
        flags=list(flags),
        dropped=list(dropped),
        validation=validation,
        validation_error=validation_error,
    )


# ---- facts ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FactRef:
    path: str
    kind: FactKind
    section: str | None
    """``allergies`` / ``medications`` / ``problems``; ``None`` for patient facts."""
    value: BaseModel | None
    """The stated fact (an item's ``extracted`` part); ``None`` for a derived-only value."""
    item_id: UUID | None = None
    derived: BaseModel | None = None
    """The derived value (D-10) for ``patient.birth_date`` / ``patient.gender``."""
    codings: tuple[BaseModel, ...] = ()


_ITEM_KIND: Final[dict[str, FactKind]] = {
    "allergies": "allergy",
    "medications": "medication",
    "problems": "condition",
}


def _derived(enriched: EnrichedIps, name: str) -> BaseModel | None:
    value = getattr(getattr(enriched, "patient_derived", None), name, None)
    return value if isinstance(value, BaseModel) else None


def iter_facts(enriched: EnrichedIps) -> Iterator[FactRef]:
    """Every reviewable fact in document-model order (patient first)."""
    patient = enriched.patient
    for i, name in enumerate(patient.names):
        yield FactRef(f"patient.names[{i}]", "patient_name", None, name)
    for i, identifier in enumerate(patient.identifiers):
        yield FactRef(f"patient.identifiers[{i}]", "patient_identifier", None, identifier)
    birth_derived = _derived(enriched, "birth_date")
    if patient.birth_date is not None or birth_derived is not None:
        yield FactRef(
            "patient.birth_date",
            "patient_birth_date",
            None,
            patient.birth_date,
            None,
            birth_derived,
        )
    gender_derived = _derived(enriched, "gender")
    if patient.gender is not None or gender_derived is not None:
        yield FactRef(
            "patient.gender", "patient_gender", None, patient.gender, None, gender_derived
        )

    for key in SECTION_KEYS:
        section = getattr(enriched, key)
        if section.kind == "none_known":
            yield FactRef(key, "section_none_known", key, section)
            continue
        if section.kind != "items_found":
            continue
        for i, item in enumerate(section.items):
            enriched_item = cast(Enriched[Any], item)
            yield FactRef(
                f"{key}.items[{i}]",
                _ITEM_KIND[key],
                key,
                enriched_item.extracted,
                enriched_item.id,
                codings=tuple(enriched_item.codings),
            )
        for i, statement in enumerate(getattr(section, "none_known_statements", [])):
            yield FactRef(
                f"{key}.none_known_statements[{i}]", "no_known_allergy_statement", key, statement
            )


def find_fact(enriched: EnrichedIps, path: str) -> FactRef:
    for fact in iter_facts(enriched):
        if fact.path == path:
            return fact
    raise ReviewError("unknown_path", "No reviewable fact at this path.", path)


# ---- path helpers on JSON data ----------------------------------------------------------------


def _parse(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for part in path.split("."):
        match = _PATH_PART.fullmatch(part)
        if match is None:
            raise ReviewError("unknown_path", "Malformed fact path.", path)
        parts.append(match.group(1))
        if match.group(2) is not None:
            parts.append(int(match.group(2)))
    return parts


def _get(data: Any, parts: list[str | int]) -> Any:
    for part in parts:
        data = data[part]
    return data


def _set(data: Any, parts: list[str | int], value: Any) -> None:
    _get(data, parts[:-1])[parts[-1]] = value


def _value_parts(fact: FactRef) -> list[str | int]:
    """JSON path of the fact's stated value inside an ``EnrichedIps`` dump."""
    parts = _parse(fact.path)
    return [*parts, "extracted"] if fact.item_id is not None else parts


# ---- actions ----------------------------------------------------------------------------------


def apply_actions(
    state: DraftState, actions: list[ReviewAction], *, actor: str, now: dt.datetime
) -> DraftState:
    """Apply reviewer actions in order; all or nothing (raises `ReviewError`)."""
    data = state.current.model_dump(mode="json")
    reviews = {path: review.model_copy() for path, review in state.reviews.items()}
    pipeline_data = state.pipeline.model_dump(mode="json")

    for action in actions:
        fact = find_fact(EnrichedIps.model_validate(data), action.path)
        review = reviews.get(action.path) or FactReview()
        if isinstance(action, EditAction):
            _apply_edit(data, pipeline_data, state.pipeline, fact, action)
            review = review.model_copy(update={"decision": Decision.EDITED})
        elif isinstance(action, ConfirmAction):
            _apply_confirm(data, fact, action)
            review = review.model_copy(update={"confirmed": True})
        elif isinstance(action, ResetAction):
            parts = _value_parts(fact)
            _set(data, parts, _get(pipeline_data, parts))
            if fact.item_id is not None:
                item_parts = _parse(fact.path)
                _set(data, [*item_parts, "codings"], _get(pipeline_data, [*item_parts, "codings"]))
            review = FactReview()
        elif isinstance(action, RejectAction):
            review = review.model_copy(update={"decision": Decision.REJECTED})
        else:  # accept
            decision = Decision.EDITED if review.decision is Decision.EDITED else Decision.ACCEPTED
            review = review.model_copy(update={"decision": decision})
        reviews[action.path] = review.model_copy(update={"by": actor, "at": now})

    try:
        current = EnrichedIps.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - each edit is validated on its own
        raise ReviewError("invalid_edit", "The edited draft is not valid.") from exc
    return state.model_copy(update={"current": current, "reviews": reviews})


def _apply_edit(
    data: dict[str, Any],
    pipeline_data: dict[str, Any],
    pipeline: EnrichedIps,
    fact: FactRef,
    action: EditAction,
) -> None:
    if fact.value is None:
        raise ReviewError(
            "derived_not_editable",
            "A derived value can be confirmed or rejected, not edited.",
            fact.path,
        )
    model = type(fact.value)
    value = dict(action.value)
    if isinstance(fact.value, NoneKnown | NoKnownAllergies):
        value["kind"] = "none_known"
    try:
        new = model.model_validate(value)
    except ValidationError as exc:
        # Report locations and error types only: the input may contain patient data.
        details = ", ".join(
            ".".join(str(p) for p in err["loc"]) + f" ({err['type']})" for err in exc.errors()
        )
        raise ReviewError("invalid_edit", f"Invalid value: {details}", fact.path) from exc

    try:
        original = find_fact(pipeline, fact.path).value
    except ReviewError:  # pragma: no cover - paths are stable between pipeline and current
        original = None
    for name in _PROVENANCE_FIELDS:
        if (
            original is not None
            and name in type(original).model_fields
            and getattr(new, name) != getattr(original, name)
        ):
            raise ReviewError(
                "provenance_changed",
                f"'{name}' cannot be edited: provenance stays as extracted.",
                fact.path,
            )

    parts = _value_parts(fact)
    _set(data, parts, new.model_dump(mode="json"))
    if fact.item_id is not None:
        _drop_stale_codings(data, _parse(fact.path), fact.value, new)


def _drop_stale_codings(
    data: dict[str, Any], item_parts: list[str | int], old: BaseModel, new: BaseModel
) -> None:
    """Keep terminology codes only for text fields the edit did not change."""
    kept = []
    for field_coding in _get(data, [*item_parts, "codings"]):
        path = field_coding["path"]
        try:
            unchanged = resolve_path(old, path) == resolve_path(new, path)
        except ValueError:
            unchanged = False
        if unchanged:
            kept.append(field_coding)
    _set(data, [*item_parts, "codings"], kept)


def _apply_confirm(data: dict[str, Any], fact: FactRef, action: ConfirmAction) -> None:
    if isinstance(fact.value, AllergyItem):
        status = action.clinical_status or AllergyClinicalStatus.ACTIVE.value
        _set(data, [*_value_parts(fact), "clinical_status"], status)
        return
    if action.clinical_status is not None:
        raise ReviewError(
            "invalid_confirm", "clinical_status applies to allergy items only.", fact.path
        )
    if fact.derived is None:
        raise ReviewError(
            "nothing_to_confirm",
            "Only derived patient values and allergy statuses need confirmation.",
            fact.path,
        )


# ---- effective draft ------------------------------------------------------------------------


@dataclass(frozen=True)
class Effective:
    enriched: EnrichedIps
    path_map: dict[str, str]
    """Effective path (``problems.items[0]``) -> draft path (``problems.items[2]``)."""


def effective_enriched(state: DraftState) -> Effective:
    """``current`` with rejected facts removed, as assembled into the Bundle.

    A rejected section statement, or a section whose items are all rejected, becomes
    ``no_information`` (never "none known": the reviewer only said the facts are wrong).
    """
    data = state.current.model_dump(mode="json")
    path_map: dict[str, str] = {}
    # The review screens do not show the optional sections of schema 1.2.0 (vital signs, social
    # history, immunizations, pregnancy, patient contacts) yet. Nothing the reviewer cannot see
    # may reach an approved Bundle, so they are left out here; ``assemble`` itself maps them.
    for name in UNREVIEWED_SECTIONS:
        data[name] = []
    data["patient"]["contacts"] = []

    patient = data["patient"]
    for name in ("names", "identifiers"):
        kept: list[Any] = []
        for i, value in enumerate(patient[name]):
            if not state.is_rejected(f"patient.{name}[{i}]"):
                path_map[f"patient.{name}[{len(kept)}]"] = f"patient.{name}[{i}]"
                kept.append(value)
        patient[name] = kept
    derived = data.get("patient_derived")
    for name in ("birth_date", "gender"):
        if state.is_rejected(f"patient.{name}"):
            patient[name] = None
            if isinstance(derived, dict) and name in derived:
                derived[name] = None

    for key in SECTION_KEYS:
        section = data[key]
        if section["kind"] == "none_known" and state.is_rejected(key):
            data[key] = {"kind": "no_information"}
            continue
        if section["kind"] != "items_found":
            continue
        items: list[Any] = []
        for i, item in enumerate(section["items"]):
            if not state.is_rejected(f"{key}.items[{i}]"):
                path_map[f"{key}.items[{len(items)}]"] = f"{key}.items[{i}]"
                items.append(item)
        if not items:
            data[key] = {"kind": "no_information"}
            continue
        section["items"] = items
        if "none_known_statements" in section:
            statements: list[Any] = []
            for i, statement in enumerate(section["none_known_statements"]):
                if not state.is_rejected(f"{key}.none_known_statements[{i}]"):
                    path_map[f"{key}.none_known_statements[{len(statements)}]"] = (
                        f"{key}.none_known_statements[{i}]"
                    )
                    statements.append(statement)
            section["none_known_statements"] = statements
    return Effective(EnrichedIps.model_validate(data), path_map)


_PREFIX_RE: Final = re.compile(
    r"^((?:patient|allergies|medications|problems)\.[a-z_]+\[\d+\])(.*)$"
)


def map_back(effective_path: str, path_map: dict[str, str]) -> str:
    """Translate a path of the effective draft (e.g. an assembly note's) to the draft path."""
    match = _PREFIX_RE.match(effective_path)
    if match and match.group(1) in path_map:
        return path_map[match.group(1)] + match.group(2)
    return effective_path


# ---- approval -----------------------------------------------------------------------------------


def needs_confirmation(state: DraftState, fact: FactRef) -> bool:
    if state.is_rejected(fact.path):
        return False
    if fact.derived is not None:
        return not state.review(fact.path).confirmed
    return (
        isinstance(fact.value, AllergyItem)
        and fact.value.clinical_status is AllergyClinicalStatus.NOT_STATED
    )


def approval_blockers(state: DraftState) -> list[Blocker]:
    """Why the draft cannot be approved yet (D-4: name and birth date; D-10: confirmations)."""
    effective = effective_enriched(state).enriched
    blockers: list[Blocker] = []
    if not effective.patient.names:
        blockers.append(
            Blocker(
                code=BlockerCode.PATIENT_NAME_MISSING,
                path="patient.names",
                message="The patient's name is missing.",
            )
        )
    if effective.patient.birth_date is None and _derived(effective, "birth_date") is None:
        blockers.append(
            Blocker(
                code=BlockerCode.PATIENT_BIRTH_DATE_MISSING,
                path="patient.birth_date",
                message="The patient's birth date is missing.",
            )
        )
    for fact in iter_facts(state.current):
        if fact.derived is not None and needs_confirmation(state, fact):
            blockers.append(
                Blocker(
                    code=BlockerCode.DERIVED_VALUE_UNCONFIRMED,
                    path=fact.path,
                    message="A value derived from the personal identity code must be "
                    "confirmed or rejected.",
                )
            )
    return blockers
