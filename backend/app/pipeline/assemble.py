"""Step 6: deterministic assembly of the IPS document Bundle from ``EnrichedIps``.

Pure function, no I/O, no LLM, no logging (D1). The section mappers live in ``app.fhir``
(``patient``, ``allergies``, ``medications``, ``problems``, ``immunizations``, ``results``,
``procedures``, ``devices``, ``pregnancy``, ``social_history``, ``vital_signs``, ``device``,
``composition``); this
module wires them together:

* Bundle ``type`` ``document``, ``identifier`` (``urn:ietf:rfc:3986`` + ``urn:uuid``),
  ``timestamp`` = ``now``; entries: Composition first, then Patient, the author Device, and the
  section resources in section order (Allergies, Medications, Problem List, History of Past
  Illness). Every entry's ``fullUrl`` is ``urn:uuid:<id>``.
* Ids: an enriched item keeps its stable ``id`` (so the review UI can link a resource back to
  its item across re-assemblies). Resources without one (Composition, Patient, known-absent
  statements, Bundle) get ``new_id(role)``; the default derives them with UUIDv5 from a hash of
  the input, so the same input always gives the same Bundle. The Device id depends only on the
  pipeline name and version.
* ``AssemblyResult`` carries, besides the Bundle, one ``AssemblyEntry`` per mapped fact (source
  path + item id -> fullUrl + section) with the grounding review flags for that fact, and
  mapping notes (no document content in them).

Validate the Bundle with ``app.pipeline.validate``; per PLAN, an entry in
``ValidationResult.unmatched_bundle_entries`` is a failure even with 0 errors.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

from app.fhir.allergies import map_allergy_section
from app.fhir.common import (
    IdFactory,
    MappedResource,
    MappingContext,
    MappingNote,
    NoteCode,
    SectionResult,
    reference,
    urn_uuid,
)
from app.fhir.composition import build_composition
from app.fhir.constants import PROFILE_BUNDLE, URI_IDENTIFIER_SYSTEM
from app.fhir.device import PipelineInfo, map_pipeline_device
from app.fhir.devices import map_devices
from app.fhir.immunizations import map_immunizations
from app.fhir.medications import map_medication_section
from app.fhir.models import Bundle, BundleEntry, Identifier, Meta
from app.fhir.patient import map_patient
from app.fhir.pregnancy import map_pregnancy
from app.fhir.problems import map_problem_sections
from app.fhir.procedures import map_procedures
from app.fhir.results import map_results
from app.fhir.social_history import map_social_history
from app.fhir.vital_signs import map_vital_signs
from app.pipeline.ground import ReviewFlag, ReviewReason
from app.schemas.intermediate import EnrichedIps

__all__ = [
    "AssemblyEntry",
    "AssemblyNote",
    "AssemblyResult",
    "assemble",
    "seeded_id_factory",
]


class AssemblyEntry(BaseModel):
    """Which fact of ``EnrichedIps`` became which Bundle entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    """Source path in ``EnrichedIps`` (``allergies.items[0]``, ``medications`` for a
    none_known section, ``allergies.none_known_statements[0]``, ``patient``)."""
    item_id: UUID | None
    full_url: str
    resource_type: str
    section: str | None
    """``allergies``, ``medications``, ``problems``, ``past_illness``, ``immunizations``,
    ``results``, ``procedures``, ``devices``, ``pregnancy``, ``social_history``,
    ``vital_signs``; ``None`` for Patient."""
    review_flags: tuple[ReviewReason, ...] = ()


class AssemblyNote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    code: NoteCode
    message: str
    """Describes the mapping only; never contains document content."""
    severity: Literal["info", "warning"]


class AssemblyResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle: Bundle
    entries: tuple[AssemblyEntry, ...]
    notes: tuple[AssemblyNote, ...]

    @property
    def warnings(self) -> list[AssemblyNote]:
        return [n for n in self.notes if n.severity == "warning"]

    def full_url_for(self, item_id: UUID) -> str | None:
        """fullUrl of the resource made from the enriched item ``item_id``."""
        return next((e.full_url for e in self.entries if e.item_id == item_id), None)

    def entry_for_path(self, path: str) -> AssemblyEntry | None:
        return next((e for e in self.entries if e.path == path), None)


def seeded_id_factory(seed: UUID) -> IdFactory:
    """Deterministic ids: UUIDv5 of ``role`` in the namespace ``seed``."""

    def new_id(role: str) -> UUID:
        return uuid5(seed, role)

    return new_id


def _default_seed(enriched: EnrichedIps) -> UUID:
    digest = hashlib.sha256(enriched.model_dump_json().encode("utf-8")).hexdigest()
    return uuid5(NAMESPACE_URL, f"ips-generator:assemble:{digest}")


def assemble(
    enriched: EnrichedIps,
    *,
    now: dt.datetime,
    flags: Sequence[ReviewFlag] = (),
    new_id: IdFactory | None = None,
    pipeline: PipelineInfo | None = None,
) -> AssemblyResult:
    """Build the IPS document Bundle (draft: Composition ``preliminary``) from ``enriched``.

    ``now`` (timezone-aware) is the Bundle timestamp and Composition date. ``flags`` are the
    grounding review flags (``ground.apply_grounding``); they are attached to the matching
    entries. ``new_id`` overrides id generation (default: derived from the input).
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware (FHIR instant)")
    timestamp = now.isoformat(timespec="seconds")
    ids = new_id or seeded_id_factory(_default_seed(enriched))
    pipeline = pipeline or PipelineInfo()

    patient, notes = map_patient(
        enriched.patient, resource_id=ids("patient"), derived=enriched.patient_derived
    )
    device = map_pipeline_device(pipeline, schema_version=enriched.schema_version)
    document_date = enriched.document_date.value if enriched.document_date else None
    ctx = MappingContext(
        patient=reference(patient.full_url),
        new_id=ids,
        document_date=document_date if document_date and len(document_date) == 10 else None,
    )
    # IPS order: the required sections (Problem List, Allergies, Medication Summary), then the
    # optional ones as they have content: Immunizations, History of Past Illness, Results,
    # Procedures, Medical Devices, History of Pregnancy, Social History, Vital Signs (D-14: none
    # of these is emitted when empty).
    problem_sections = map_problem_sections(enriched.problems, ctx)
    optional = (
        map_immunizations(enriched.immunizations, ctx),
        *problem_sections[1:],
        map_results(enriched.results, ctx),
        map_procedures(enriched.procedures, ctx),
        map_devices(enriched.devices, ctx),
        map_pregnancy(enriched.pregnancy, ctx),
        map_social_history(enriched.social_history, ctx),
        map_vital_signs(enriched.vital_signs, ctx),
    )
    sections: list[SectionResult] = [
        problem_sections[0],
        map_allergy_section(enriched.allergies, ctx),
        map_medication_section(enriched.medications, ctx),
        *(r for r in optional if r is not None),
    ]
    for result in sections:
        notes += result.notes
    notes += [
        MappingNote(
            path=flag.path,
            code=NoteCode.SECTION_UNVERIFIED,
            message="Grounding could not verify this section; emitted as 'no information'.",
        )
        for flag in flags
        if flag.reason is ReviewReason.SECTION_UNVERIFIED
    ]

    composition = build_composition(
        resource_id=ids("composition"),
        patient_url=patient.full_url,
        author_url=device.full_url,
        author_name=pipeline.name,
        date=timestamp,
        sections=[s.section for s in sections],
    )

    bundle_entries: dict[str, MappedResource] = {}
    for mapped in (composition, patient, device):
        bundle_entries[mapped.full_url] = mapped
    records = [_record(patient, None, flags)]
    for result in sections:
        for mapped in result.entries:
            bundle_entries.setdefault(mapped.full_url, mapped)
            records.append(_record(mapped, result.key, flags))

    bundle_id = ids("bundle")
    bundle = Bundle(
        id=str(bundle_id),
        meta=Meta(profile=[PROFILE_BUNDLE]),
        identifier=Identifier(system=URI_IDENTIFIER_SYSTEM, value=urn_uuid(bundle_id)),
        type="document",
        timestamp=timestamp,
        entry=[BundleEntry(full_url=url, resource=m.resource) for url, m in bundle_entries.items()],
    )
    return AssemblyResult(
        bundle=bundle,
        entries=tuple(records),
        notes=tuple(
            AssemblyNote(path=n.path, code=n.code, message=n.message, severity=n.severity)
            for n in notes
        ),
    )


def _record(
    mapped: MappedResource, section: str | None, flags: Sequence[ReviewFlag]
) -> AssemblyEntry:
    def matches(flag_path: str) -> bool:
        # Patient facts (``patient.names[0]``, ...) all belong to the one Patient resource.
        if mapped.path == "patient":
            return flag_path == "patient" or flag_path.startswith("patient.")
        return flag_path == mapped.path

    return AssemblyEntry(
        path=mapped.path,
        item_id=mapped.item_id,
        full_url=mapped.full_url,
        resource_type=mapped.resource.resource_type,
        section=section,
        review_flags=tuple(f.reason for f in flags if matches(f.path)),
    )
