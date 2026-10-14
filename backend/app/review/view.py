"""Build the review API view (`DraftOut`) of a stored draft, and the Bundle to approve."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.fhir.device import PipelineInfo
from app.pipeline.assemble import AssemblyNote, AssemblyResult, assemble
from app.review.draft import (
    FLAT_SECTIONS,
    SECTION_KEYS,
    DraftState,
    Effective,
    FactRef,
    approval_blockers,
    effective_enriched,
    find_fact,
    iter_facts,
    map_back,
    needs_confirmation,
)
from app.schemas.api import (
    Decision,
    DocumentInfoOut,
    DraftOut,
    FactOut,
    FlagCode,
    JobStatus,
    NoteOut,
    PatientOut,
    SectionKey,
    SectionOut,
    SourceRef,
)
from app.schemas.intermediate import AllergyClinicalStatus, AllergyItem, Confidence

__all__ = ["ApprovedInfo", "assemble_effective", "build_draft_view"]

_TITLES: dict[SectionKey, str] = {
    "allergies": "Allergies and intolerances",
    "medications": "Medication summary",
    "problems": "Problem list",
    "past_illness": "History of past illness",
    "immunizations": "Immunizations",
    "pregnancy": "History of pregnancy",
    "social_history": "Social history",
    "vital_signs": "Vital signs",
}
_FLAG_VALUES = {f.value for f in FlagCode}
SectionKind = Literal["items_found", "none_known", "no_information"]


@dataclass(frozen=True, slots=True)
class ApprovedInfo:
    at: dt.datetime
    attester_mode: Literal["personal", "professional"]


def assemble_effective(state: DraftState, *, now: dt.datetime) -> AssemblyResult:
    """The Bundle the draft stands for right now (rejections applied)."""
    effective = effective_enriched(state)
    return assemble(effective.enriched, now=now)


def _source(state: DraftState, fact: FactRef) -> SourceRef | None:
    value: BaseModel | None = fact.value
    if value is None and fact.derived is not None:
        # A derived value is quoted where its identifier is (D-10).
        source_path = getattr(getattr(fact.derived, "derivation", None), "source_path", None)
        if isinstance(source_path, str):
            try:
                value = find_fact(state.current, source_path).value
            except ValueError:
                value = None
    if value is None or not hasattr(value, "source_quote"):
        return None
    return SourceRef(
        quote=value.source_quote,
        page=getattr(value, "page", 1),
        locator=getattr(value, "locator", None),
    )


def _flag(value: str) -> FlagCode:
    return FlagCode(value) if value in _FLAG_VALUES else FlagCode.OTHER


def _fact_out(state: DraftState, fact: FactRef, notes: list[tuple[str, AssemblyNote]]) -> FactOut:
    review = state.review(fact.path)
    flags = [_flag(f.reason.value) for f in state.flags if f.path == fact.path]
    if (
        isinstance(fact.value, AllergyItem)
        and fact.value.clinical_status is AllergyClinicalStatus.NOT_STATED
    ):
        flags.append(FlagCode.ASSUMED_STATUS)
    if getattr(fact.value, "confidence", None) is Confidence.LOW:
        flags.append(FlagCode.LOW_CONFIDENCE)
    if review.decision is Decision.EDITED:
        flags.append(FlagCode.EDITED)

    pipeline_value: dict[str, Any] | None = None
    if review.decision is Decision.EDITED:
        original = find_fact(state.pipeline, fact.path).value
        pipeline_value = original.model_dump(mode="json") if original is not None else None

    derived: dict[str, Any] | None = None
    if fact.derived is not None:
        derived = fact.derived.model_dump(mode="json")

    fact_notes = [
        NoteOut(code=n.code.value, message=n.message, severity=n.severity)
        for path, n in notes
        if path == fact.path or path.startswith((fact.path + ".", fact.path + "["))
    ]
    return FactOut(
        path=fact.path,
        item_id=fact.item_id,
        kind=fact.kind,
        value=fact.value.model_dump(mode="json") if fact.value is not None else {},
        pipeline_value=pipeline_value,
        source=_source(state, fact),
        derived=derived,
        decision=review.decision,
        needs_confirmation=needs_confirmation(state, fact),
        confirmed=review.confirmed,
        flags=list(dict.fromkeys(flags)),
        notes=fact_notes,
        codings=[c.model_dump(mode="json") for c in fact.codings],
    )


def _flat_section(
    key: SectionKey,
    facts: list[FactRef],
    outs: dict[str, FactOut],
    effective: Effective,
) -> SectionOut | None:
    items = [outs[f.path] for f in facts if f.section == key]
    if not items:
        return None
    kept = bool(getattr(effective.enriched, key))
    return SectionOut(
        key=key,
        title=_TITLES[key],
        kind="items_found",
        effective_kind="items_found" if kept else "no_information",
        statement=None,
        items=items,
        scoped_statements=[],
        flags=[],
    )


def build_draft_view(
    state: DraftState,
    *,
    job_id: UUID,
    version: int,
    status: JobStatus,
    now: dt.datetime,
    created_at: dt.datetime | None = None,
    approved: ApprovedInfo | None = None,
) -> DraftOut:
    effective = effective_enriched(state)
    assembly = assemble(effective.enriched, now=now)
    notes = [(map_back(n.path, effective.path_map), n) for n in assembly.notes]
    # Routing of conditions (D-8) for every item, rejected ones included.
    routing = assemble(state.current, now=now)
    section_of: dict[UUID, str | None] = {
        e.item_id: e.section for e in routing.entries if e.item_id is not None
    }

    facts = list(iter_facts(state.current))
    outs = {fact.path: _fact_out(state, fact, notes) for fact in facts}
    attached = {
        path
        for path, _ in notes
        for fact_path in outs
        if path == fact_path or path.startswith((fact_path + ".", fact_path + "["))
    }

    patient = PatientOut(
        names=[outs[f.path] for f in facts if f.kind == "patient_name"],
        identifiers=[outs[f.path] for f in facts if f.kind == "patient_identifier"],
        contacts=[outs[f.path] for f in facts if f.kind == "patient_contact"],
        birth_date=outs.get("patient.birth_date"),
        gender=outs.get("patient.gender"),
        flags=[
            _flag(f.reason.value)
            for f in state.flags
            if f.path.startswith("patient") and f.path not in outs
        ],
    )

    sections: list[SectionOut] = []
    past_section: SectionOut | None = None
    for key in SECTION_KEYS:
        section = getattr(state.current, key)
        effective_section = getattr(effective.enriched, key)
        section_flags = [_flag(f.reason.value) for f in state.flags if f.path == key]
        items = [outs[f.path] for f in facts if f.section == key and f.item_id is not None]
        scoped = [outs[f.path] for f in facts if f.kind == "no_known_allergy_statement"]
        statement = outs.get(key) if section.kind == "none_known" else None
        if key != "problems":
            sections.append(
                SectionOut(
                    key=key,
                    title=_TITLES[key],
                    kind=section.kind,
                    effective_kind=effective_section.kind,
                    statement=statement,
                    items=items,
                    scoped_statements=scoped if key == "allergies" else [],
                    flags=section_flags,
                )
            )
            continue
        current = [i for i in items if section_of.get(i.item_id or UUID(int=0)) != "past_illness"]
        past = [i for i in items if section_of.get(i.item_id or UUID(int=0)) == "past_illness"]
        problems_kind: SectionKind = section.kind
        effective_kind: SectionKind = effective_section.kind
        if section.kind == "items_found" and not current:
            problems_kind = "no_information"
        if effective_kind == "items_found" and all(
            i.decision is Decision.REJECTED for i in current
        ):
            effective_kind = "no_information"
        sections.append(
            SectionOut(
                key="problems",
                title=_TITLES["problems"],
                kind=problems_kind,
                effective_kind=effective_kind,
                statement=statement,
                items=current,
                scoped_statements=[],
                flags=section_flags,
            )
        )
        if past:
            past_section = SectionOut(
                key="past_illness",
                title=_TITLES["past_illness"],
                kind="items_found",
                effective_kind=(
                    "no_information"
                    if all(i.decision is Decision.REJECTED for i in past)
                    else "items_found"
                ),
                statement=None,
                items=past,
                scoped_statements=[],
                flags=[],
            )
    # IPS order after the required sections: Immunizations, History of Past Illness, History of
    # Pregnancy, Social History, Vital Signs (a flat section is listed only when it has items).
    flat_sections = {key: _flat_section(key, facts, outs, effective) for key in FLAT_SECTIONS}
    if (immunizations := flat_sections["immunizations"]) is not None:
        sections.append(immunizations)
    if past_section is not None:
        sections.append(past_section)
    sections.extend(
        section
        for key in ("pregnancy", "social_history", "vital_signs")
        if (section := flat_sections[key]) is not None
    )

    pipeline = PipelineInfo()
    return DraftOut(
        job_id=job_id,
        version=version,
        status=status,
        document=DocumentInfoOut(
            software=pipeline.name,
            software_version=pipeline.version,
            ai_assisted=True,
            created_at=created_at or now,
            approved_at=approved.at if approved else None,
            attester_mode=approved.attester_mode if approved else None,
        ),
        document_language=state.current.document_language,
        patient=patient,
        document_date=outs.get("document_date"),
        sections=sections,
        notes=[
            NoteOut(code=n.code.value, message=n.message, severity=n.severity)
            for path, n in notes
            if path not in attached
        ],
        dropped_paths=list(state.dropped),
        blockers=approval_blockers(state),
        validation=state.validation,
        validation_error=state.validation_error,
    )
