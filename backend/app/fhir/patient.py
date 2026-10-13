"""Patient mapper (Patient-uv-ips).

* ``name`` 1..* and ips-pat-1 (``family``, ``given`` or ``text``): each extracted name becomes a
  ``HumanName`` with the name as written in ``text`` plus ``family``/``given`` when the
  extraction split them. With no extracted name, one ``HumanName`` whose ``_text`` carries a
  data-absent-reason extension is emitted (validates in Matchbox) and a warning is recorded:
  never a made-up name.
* ``birthDate`` 1..1: with no extracted birth date (D-10 still open), ``_birthDate`` carries a
  data-absent-reason extension (``unknown``; validates in Matchbox) and a warning is recorded.
  Phase 3 blocks approval until name and birth date are present (D-4).
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
from app.schemas.intermediate import AdministrativeGender, PatientExtraction

PATH = "patient"

_GENDER: dict[AdministrativeGender, Literal["male", "female", "other", "unknown"]] = {
    AdministrativeGender.MALE: "male",
    AdministrativeGender.FEMALE: "female",
    AdministrativeGender.OTHER: "other",
    AdministrativeGender.UNKNOWN: "unknown",
}


def map_patient(
    patient: PatientExtraction, *, resource_id: UUID
) -> tuple[MappedResource, list[MappingNote]]:
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

    details: list[tuple[str, str]] = [
        ("birth date", birth_date or "unknown"),
        ("gender", gender or "not stated"),
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
