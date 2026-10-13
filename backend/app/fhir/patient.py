"""Patient mapper (Patient-uv-ips).

* ``name`` 1..* and ips-pat-1 (``family``, ``given`` or ``text``): each extracted name becomes a
  ``HumanName`` with the name as written in ``text`` plus ``family``/``given`` when the
  extraction split them. With no extracted name, one ``HumanName`` whose ``_text`` carries a
  data-absent-reason extension is emitted (validates in Matchbox) and a warning is recorded:
  never a made-up name.
* ``birthDate`` 1..1: the stated birth date, or the one derived from a Finnish personal identity
  code (D-10, ``EnrichedIps.patient_derived``; ``app.pipeline.derive`` only derives when the
  document states none, or completes a consistent partial date). With neither, ``_birthDate``
  carries a data-absent-reason extension (``unknown``; validates in Matchbox) and a warning is
  recorded. Phase 3 blocks approval until name and birth date are present (D-4).
* ``gender``: stated, else derived (D-10), else absent. The mapper itself also never lets a
  derived value replace a stated one.
* Derived values: FHIR R4 / IPS 2.0.1 have no element or core extension that marks a primitive
  as *derived*, and we do not invent extensions. The Bundle carries the plain value; the
  derivation is recorded in ``EnrichedIps.patient_derived``, as an ``info`` mapping note
  (``birth_date_derived`` / ``gender_derived``, PHI-free) and in the Patient narrative ("derived
  from personal identity code"). Phase 5's ``Provenance`` is where it can go machine-readably.
* ``identifier``: value as written, the document's label in ``type.text`` and the issuer in
  ``assigner.display``. **No ``system``**: the schema keeps the system as text only and a URI
  must never be invented.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.fhir.common import (
    MappedResource,
    MappingNote,
    NoteCode,
    data_absent,
    urn_uuid,
)
from app.fhir.constants import PROFILE_PATIENT
from app.fhir.models import (
    CodeableConcept,
    HumanName,
    Identifier,
    Meta,
    Patient,
    PrimitiveElement,
    Reference,
)
from app.fhir.narrative import NarrativeLine, line_narrative
from app.schemas.intermediate import AdministrativeGender, PatientDerivations, PatientExtraction

PATH = "patient"

_GENDER: dict[AdministrativeGender, Literal["male", "female", "other", "unknown"]] = {
    AdministrativeGender.MALE: "male",
    AdministrativeGender.FEMALE: "female",
    AdministrativeGender.OTHER: "other",
    AdministrativeGender.UNKNOWN: "unknown",
}


_DERIVED_SUFFIX = " (derived from personal identity code)"


def _may_use(stated: str | None, derived: str) -> bool:
    """A derived birth date never replaces a stated one; it may complete a partial one."""
    return stated is None or (len(stated) < len(derived) and derived.startswith(stated))


def map_patient(
    patient: PatientExtraction,
    *,
    resource_id: UUID,
    derived: PatientDerivations | None = None,
) -> tuple[MappedResource, list[MappingNote]]:
    derived = derived or PatientDerivations()
    notes: list[MappingNote] = []
    names = [
        HumanName(text=n.text, family=n.family, given=list(n.given) or None) for n in patient.names
    ]
    if not names:
        names = [HumanName(primitive_extensions={"text": data_absent()})]
        notes.append(
            MappingNote(
                path=f"{PATH}.names",
                code=NoteCode.PATIENT_NAME_MISSING,
                message="No patient name in the source; Patient.name.text marked "
                "data-absent-reason 'unknown'.",
            )
        )

    primitive_extensions: dict[str, PrimitiveElement | list[PrimitiveElement | None]] = {}
    birth_date = patient.birth_date.value if patient.birth_date else None
    birth_date_text = birth_date
    if derived.birth_date is not None and _may_use(birth_date, derived.birth_date.value):
        birth_date = derived.birth_date.value
        birth_date_text = birth_date + _DERIVED_SUFFIX
        notes.append(
            MappingNote(
                path=f"{PATH}.birth_date",
                code=NoteCode.BIRTH_DATE_DERIVED,
                message="Patient.birthDate derived from a Finnish personal identity code "
                f"(method {derived.birth_date.derivation.method.value}"
                + (
                    ", completing a partial stated date"
                    if derived.birth_date.derivation.completes_stated
                    else ""
                )
                + "); the reviewer must confirm it.",
                severity="info",
            )
        )
    if birth_date is None:
        primitive_extensions["birthDate"] = data_absent()
        notes.append(
            MappingNote(
                path=f"{PATH}.birth_date",
                code=NoteCode.BIRTH_DATE_MISSING,
                message="No birth date in the source; Patient.birthDate (required by IPS) "
                "marked data-absent-reason 'unknown'.",
            )
        )

    identifiers = [
        Identifier(
            type=CodeableConcept(text=i.type_text) if i.type_text else None,
            value=i.value,
            assigner=Reference(display=i.issuer_text) if i.issuer_text else None,
        )
        for i in patient.identifiers
    ]
    gender = _GENDER[patient.gender.value] if patient.gender else None
    gender_text: str | None = gender
    if gender is None and derived.gender is not None:
        gender = _GENDER[derived.gender.value]
        gender_text = gender + _DERIVED_SUFFIX
        notes.append(
            MappingNote(
                path=f"{PATH}.gender",
                code=NoteCode.GENDER_DERIVED,
                message="Patient.gender derived from a Finnish personal identity code (method "
                f"{derived.gender.derivation.method.value}); the reviewer must confirm it.",
                severity="info",
            )
        )

    details: list[tuple[str, str]] = [
        ("birth date", birth_date_text or "unknown"),
        ("gender", gender_text or "not stated"),
    ]
    details += [(i.type_text or "identifier", i.value) for i in patient.identifiers]
    title = "; ".join(n.text for n in patient.names) or "Name unknown"
    line = NarrativeLine(title, tuple(details))

    resource = Patient(
        id=str(resource_id),
        meta=Meta(profile=[PROFILE_PATIENT]),
        text=line_narrative(line),
        identifier=identifiers or None,
        name=names,
        gender=gender,
        birth_date=birth_date,
        primitive_extensions=primitive_extensions or None,
    )
    return MappedResource(PATH, None, urn_uuid(resource_id), resource), notes
