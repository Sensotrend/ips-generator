"""Patient mapper: names, identifiers (HETU OID system only for a valid HETU), absent data."""

from uuid import UUID

from app.fhir.common import NoteCode
from app.fhir.constants import DATA_ABSENT_REASON_URL, HETU_IDENTIFIER_SYSTEM, PROFILE_PATIENT
from app.fhir.patient import map_patient
from tests.assembly_cases import (
    build,
    derived_birth_date,
    derived_birth_date_and_gender,
    with_birth_date,
    without_name,
)

PID = UUID("00000000-0000-4000-8000-000000000001")


def test_patient_from_fixture() -> None:
    mapped, _ = map_patient(build().patient, resource_id=PID)
    fhir = mapped.resource.to_fhir()
    assert mapped.full_url == f"urn:uuid:{PID}"
    assert mapped.path == "patient"
    assert fhir["id"] == str(PID)
    assert fhir["meta"] == {"profile": [PROFILE_PATIENT]}
    assert fhir["name"] == [
        {"text": "Virtanen, Matti Juhani", "family": "Virtanen", "given": ["Matti", "Juhani"]}
    ]
    assert fhir["gender"] == "male"


def test_valid_hetu_identifier_gets_the_hetu_oid_system() -> None:
    mapped, _ = map_patient(build().patient, resource_id=PID)
    assert HETU_IDENTIFIER_SYSTEM == "urn:oid:1.2.246.21"
    assert mapped.resource.to_fhir()["identifier"] == [
        {
            "type": {"text": "Henkilötunnus"},
            "system": HETU_IDENTIFIER_SYSTEM,
            "value": "150372-9477",
        }
    ]


def test_identifier_that_is_not_a_valid_hetu_gets_no_system() -> None:
    patient = build().patient
    patient.identifiers[0].value = "150372-9478"  # wrong check character
    patient.identifiers[0].source_quote = "Henkilötunnus: 150372-9478"
    mapped, _ = map_patient(patient, resource_id=PID)
    assert "system" not in mapped.resource.to_fhir()["identifier"][0]


def test_foreign_labelled_identifier_gets_no_system() -> None:
    patient = build().patient
    patient.identifiers[0].type_text = "Personnummer (Sweden)"
    mapped, _ = map_patient(patient, resource_id=PID)
    assert "system" not in mapped.resource.to_fhir()["identifier"][0]


def test_identifier_issuer_becomes_assigner_display() -> None:
    patient = build().patient
    patient.identifiers[0].issuer_text = "Digi- ja väestötietovirasto"
    mapped, _ = map_patient(patient, resource_id=PID)
    identifier = mapped.resource.to_fhir()["identifier"][0]
    assert identifier["assigner"] == {"display": "Digi- ja väestötietovirasto"}


def test_missing_birth_date_is_data_absent_with_warning() -> None:
    mapped, notes = map_patient(build().patient, resource_id=PID)
    fhir = mapped.resource.to_fhir()
    assert "birthDate" not in fhir
    assert fhir["_birthDate"] == {
        "extension": [{"url": DATA_ABSENT_REASON_URL, "valueCode": "unknown"}]
    }
    assert [(n.code, n.severity) for n in notes] == [(NoteCode.BIRTH_DATE_MISSING, "warning")]


def test_birth_date_partial_and_full() -> None:
    mapped, notes = map_patient(with_birth_date().patient, resource_id=PID)
    fhir = mapped.resource.to_fhir()
    assert fhir["birthDate"] == "1972-03-15"
    assert "_birthDate" not in fhir
    assert notes == []


def test_missing_name_is_data_absent_never_invented() -> None:
    mapped, notes = map_patient(without_name().patient, resource_id=PID)
    fhir = mapped.resource.to_fhir()
    assert fhir["name"] == [
        {"_text": {"extension": [{"url": DATA_ABSENT_REASON_URL, "valueCode": "unknown"}]}}
    ]
    assert NoteCode.PATIENT_NAME_MISSING in {n.code for n in notes}


def test_narrative_escapes_patient_text() -> None:
    patient = build().patient
    patient.names[0].text = "<b>Virtanen</b> & Co"
    mapped, _ = map_patient(patient, resource_id=PID)
    assert mapped.resource.text is not None
    assert "&lt;b&gt;Virtanen&lt;/b&gt; &amp; Co" in mapped.resource.text.div


def test_derived_birth_date_is_used_with_info_note() -> None:
    enriched = derived_birth_date()
    mapped, notes = map_patient(enriched.patient, resource_id=PID, derived=enriched.patient_derived)
    fhir = mapped.resource.to_fhir()
    assert fhir["birthDate"] == "1972-03-15"
    assert "_birthDate" not in fhir
    assert fhir["gender"] == "male"  # stated; the fixture's 900-999 code carries no sex
    assert [(n.code, n.severity) for n in notes] == [(NoteCode.BIRTH_DATE_DERIVED, "info")]
    assert "150372" not in notes[0].message  # no identity code in notes
    assert mapped.resource.text is not None
    assert "derived from personal identity code" in mapped.resource.text.div


def test_derived_gender_used_only_when_not_stated() -> None:
    enriched = derived_birth_date_and_gender()
    mapped, notes = map_patient(enriched.patient, resource_id=PID, derived=enriched.patient_derived)
    fhir = mapped.resource.to_fhir()
    assert fhir["birthDate"] == "1840-01-01"
    assert fhir["gender"] == "male"
    assert {n.code for n in notes} == {NoteCode.BIRTH_DATE_DERIVED, NoteCode.GENDER_DERIVED}


def test_stated_values_win_over_derived() -> None:
    enriched = with_birth_date()  # stated 1972-03-15, gender male
    derived = derived_birth_date_and_gender().patient_derived  # 1840-01-01, male
    mapped, notes = map_patient(enriched.patient, resource_id=PID, derived=derived)
    fhir = mapped.resource.to_fhir()
    assert fhir["birthDate"] == "1972-03-15"
    assert fhir["gender"] == "male"
    assert notes == []
