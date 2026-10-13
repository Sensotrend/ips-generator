"""Jobs API end to end, in process: upload -> pipeline (replay extractor) -> review -> approve."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import ExtractorKind, Settings
from app.db.models import AuditEvent, ReviewActionRecord
from app.fhir.models import Bundle
from app.main import create_app
from app.pipeline.run import DeriveOutcome, PipelineHooks
from app.pipeline.validate import MatchboxError, ValidationIssue, ValidationResult
from app.schemas.intermediate import EnrichedIps
from app.services import ConfigError, Services
from tests.api_support import DATASET, dataset_document, make_services

TXT_CASE = "fi01_discharge_internal_txt"  # name + birth date stated
CSV_CASE = "fi12_lab_results_comma_csv"  # name, no birth date (HETU only)
PDF_CASE = "en01_discharge_resp_pdf"


def _client(services: Services) -> TestClient:
    return TestClient(create_app(services))


@pytest.fixture
def services() -> Services:
    return make_services()


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with _client(services) as c:
        yield c


def _upload(client: TestClient, case_id: str, content_type: str | None = None) -> dict[str, Any]:
    path = dataset_document(case_id)
    files = {"file": (path.name, path.read_bytes(), content_type or "application/octet-stream")}
    response = client.post("/api/jobs", files=files)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _job_id(client: TestClient, case_id: str) -> str:
    job = _upload(client, case_id)
    assert job["status"] == "review", job
    return str(job["id"])


# ---- upload / job ---------------------------------------------------------------------------


def test_upload_runs_pipeline_to_review(client: TestClient) -> None:
    job = _upload(client, TXT_CASE)
    assert job["status"] == "review"
    assert job["media_type"] == "text/plain"
    assert job["draft_version"] == 1
    again = client.get(f"/api/jobs/{job['id']}")
    assert again.status_code == 200
    assert again.headers["cache-control"] == "no-store"
    assert [j["id"] for j in client.get("/api/jobs").json()] == [job["id"]]


def test_unknown_document_fails_with_phi_free_error(client: TestClient) -> None:
    phi = "Potilas: Salainen Henkilö, synt. 01.01.1950"
    response = client.post("/api/jobs", files={"file": ("x.txt", phi.encode(), "text/plain")})
    job = response.json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "replay_no_answer"
    assert "eval documents" in job["error"]["message"]
    assert "Salainen" not in response.text


def test_unsupported_and_empty_uploads(client: TestClient) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    response = client.post("/api/jobs", files={"file": ("photo.png", png, "image/png")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    response = client.post("/api/jobs", files={"file": ("a.txt", b"  \n", "text/plain")})
    assert response.json()["error"]["code"] == "empty_document"
    response = client.post("/api/jobs", files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
    assert response.json()["error"]["code"] == "corrupt_document"


def test_unknown_job_is_404(client: TestClient) -> None:
    response = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_events_stream_replays_steps_until_review(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    steps = [(e["step"], e["status"]) for e in events]
    assert steps[0] == ("job", "queued")
    assert ("ingest", "completed") in steps
    assert ("extract", "completed") in steps
    assert ("derive", "skipped") in steps
    assert ("terminology", "skipped") in steps
    assert ("validate", "skipped") in steps
    assert steps[-1] == ("job", "review_ready")
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    # Resume after the last seen id: nothing before it is sent again.
    with client.stream(
        "GET", f"/api/jobs/{job_id}/events", headers={"Last-Event-ID": str(events[-2]["seq"])}
    ) as response:
        resumed = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert len(resumed) == 1
    # Resuming after the terminal event ends the stream instead of waiting forever.
    with client.stream(
        "GET", f"/api/jobs/{job_id}/events", headers={"Last-Event-ID": str(events[-1]["seq"])}
    ) as response:
        assert [line for line in response.iter_lines() if line.startswith("data: ")] == []


# ---- source ---------------------------------------------------------------------------------


def test_source_segments_and_original(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    source = client.get(f"/api/jobs/{job_id}/source").json()
    assert source["media_type"] == "text/plain"
    assert source["original_url"] is None
    assert any(s["locator"] == "line 6" for s in source["segments"])

    pdf_job = _job_id(client, PDF_CASE)
    pdf_source = client.get(f"/api/jobs/{pdf_job}/source").json()
    assert pdf_source["original_url"] == f"/api/jobs/{pdf_job}/source/original"
    original = client.get(pdf_source["original_url"])
    assert original.headers["content-type"] == "application/pdf"
    assert original.headers["cache-control"] == "no-store"
    assert original.content == dataset_document(PDF_CASE).read_bytes()


# ---- draft review ---------------------------------------------------------------------------


def _draft(client: TestClient, job_id: str) -> dict[str, Any]:
    response = client.get(f"/api/jobs/{job_id}/draft")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _section(draft: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in draft["sections"] if s["key"] == key)


def test_draft_view_sections_and_flags(client: TestClient) -> None:
    draft = _draft(client, _job_id(client, TXT_CASE))
    keys = [s["key"] for s in draft["sections"]]
    assert keys[:3] == ["allergies", "medications", "problems"]
    assert "past_illness" in keys  # D-8: "Keuhkokuume 2019, parantunut"
    allergy = _section(draft, "allergies")["items"][0]
    assert allergy["source"]["locator"] == "line 27"
    assert "assumed_status" in allergy["flags"]
    assert allergy["needs_confirmation"] is True
    assert draft["patient"]["birth_date"]["value"]["value"] == "1951-05-03"
    assert draft["blockers"] == []


def _put(client: TestClient, job_id: str, version: int, *actions: dict[str, Any]) -> Any:
    return client.put(f"/api/jobs/{job_id}/draft", json={"version": version, "actions": actions})


def test_review_actions_edit_reject_confirm(client: TestClient, services: Services) -> None:
    job_id = _job_id(client, TXT_CASE)
    draft = _draft(client, job_id)
    med = _section(draft, "medications")["items"][0]
    edited = {**med["value"], "strength_text": "40 mg"}
    response = _put(
        client,
        job_id,
        1,
        {"action": "edit", "path": med["path"], "value": edited},
        {"action": "reject", "path": "medications.items[1]"},
        {"action": "confirm", "path": "allergies.items[0]", "clinical_status": "active"},
        {"action": "accept", "path": "problems.items[0]"},
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["version"] == 2
    meds = _section(draft, "medications")["items"]
    assert meds[0]["decision"] == "edited"
    assert meds[0]["value"]["strength_text"] == "40 mg"
    assert meds[0]["pipeline_value"]["strength_text"] == med["value"]["strength_text"]
    assert "edited" in meds[0]["flags"]
    assert meds[1]["decision"] == "rejected"
    allergy = _section(draft, "allergies")["items"][0]
    assert allergy["value"]["clinical_status"] == "active"
    assert allergy["needs_confirmation"] is False
    assert "assumed_status" not in allergy["flags"]

    # Stale version -> conflict; reset restores the pipeline value.
    assert _put(client, job_id, 1, {"action": "accept", "path": med["path"]}).status_code == 409
    draft = _put(client, job_id, 2, {"action": "reset", "path": med["path"]}).json()
    reset = _section(draft, "medications")["items"][0]
    assert reset["decision"] == "pending"
    assert reset["value"] == med["value"]

    with services.session() as session:
        actions = session.scalars(select(ReviewActionRecord)).all()
        assert [a.action for a in actions] == ["edit", "reject", "confirm", "accept", "reset"]
        audit = session.scalars(select(AuditEvent.action)).all()
        assert "draft.updated" in audit
        # Audit details hold paths and actions, never values.
        for event in session.scalars(select(AuditEvent)).all():
            assert "40 mg" not in json.dumps(event.details)


def test_edit_cannot_change_provenance_and_errors_do_not_echo_values(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    med = _section(_draft(client, job_id), "medications")["items"][0]
    moved = {**med["value"], "source_quote": "Potilas: TESTINEN"}
    response = _put(client, job_id, 1, {"action": "edit", "path": med["path"], "value": moved})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "provenance_changed"

    bad = {**med["value"], "medication_text": "", "strength_text": "SECRET-VALUE"}
    response = _put(client, job_id, 1, {"action": "edit", "path": med["path"], "value": bad})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_edit"
    assert "SECRET-VALUE" not in response.text

    response = client.put(
        f"/api/jobs/{job_id}/draft",
        json={"version": "SECRET-VALUE", "actions": [{"action": "nope", "path": "x"}]},
    )
    assert response.status_code == 422
    assert "SECRET-VALUE" not in response.text
    response = _put(client, job_id, 1, {"action": "accept", "path": "allergies.items[9]"})
    assert response.json()["error"]["code"] == "unknown_path"


def test_rejecting_all_items_makes_section_no_information(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    draft = _put(client, job_id, 1, {"action": "reject", "path": "allergies.items[0]"}).json()
    allergies = _section(draft, "allergies")
    assert allergies["kind"] == "items_found"
    assert allergies["effective_kind"] == "no_information"


# ---- approval -------------------------------------------------------------------------------


def _approve(client: TestClient, job_id: str, version: int, role: str = "clinician") -> Any:
    return client.post(f"/api/jobs/{job_id}/approve", json={"version": version, "role": role})


def test_approve_clinician_and_download(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    assert client.get(f"/api/jobs/{job_id}/ips").json()["error"]["code"] == "not_approved"
    response = _approve(client, job_id, 1)
    assert response.status_code == 200, response.text
    approval = response.json()
    assert approval["attester_mode"] == "professional"
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "approved"

    download = client.get(approval["ips_url"])
    assert download.headers["content-type"].startswith("application/fhir+json")
    assert "attachment" in download.headers["content-disposition"]
    bundle = download.json()
    Bundle.model_validate(bundle)  # well-formed for our FHIR models
    composition = bundle["entry"][0]["resource"]
    assert composition["status"] == "final"
    assert composition["attester"][0]["mode"] == "professional"
    assert composition["attester"][0]["party"] == {"display": "Dev Reviewer"}
    # The author stays the pipeline Device (D-4).
    author = composition["author"][0]["reference"]
    devices = [e for e in bundle["entry"] if e["resource"]["resourceType"] == "Device"]
    assert [e["fullUrl"] for e in devices] == [author]

    # After approval the draft is frozen.
    assert _put(client, job_id, 1, {"action": "accept", "path": "allergies.items[0]"}).json()[
        "error"
    ]["code"] in {"already_approved", "version_conflict"}
    assert _approve(client, job_id, 1).json()["error"]["code"] == "already_approved"
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert "review_ready" in "".join(stream.iter_text())


def test_approve_as_patient_attests_personal(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    approval = _approve(client, job_id, 1, role="patient").json()
    assert approval["attester_mode"] == "personal"
    bundle = client.get(approval["ips_url"]).json()
    composition = bundle["entry"][0]["resource"]
    patient_url = composition["subject"]["reference"]
    assert composition["attester"] == [
        {
            "mode": "personal",
            "time": composition["attester"][0]["time"],
            "party": {"reference": patient_url},
        }
    ]


def test_approval_blocked_without_birth_date(client: TestClient) -> None:
    job_id = _job_id(client, CSV_CASE)
    draft = _draft(client, job_id)
    assert [b["code"] for b in draft["blockers"]] == ["patient_birth_date_missing"]
    response = _approve(client, job_id, 1)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "approval_blocked"
    assert error["details"] == [
        {"code": "patient_birth_date_missing", "path": "patient.birth_date"}
    ]


def test_approval_blocked_without_name(client: TestClient) -> None:
    job_id = _job_id(client, TXT_CASE)
    _put(client, job_id, 1, {"action": "reject", "path": "patient.names[0]"})
    codes = [d["code"] for d in _approve(client, job_id, 2).json()["error"]["details"]]
    assert codes == ["patient_name_missing"]


def _derive_birth_date(enriched: EnrichedIps) -> DeriveOutcome:
    """A stand-in for the D-10 hook: whatever the real step derives must be confirmed."""
    from app.pipeline.ground import ReviewFlag, ReviewReason
    from app.schemas.intermediate import PatientDerivations

    derived = PatientDerivations.model_validate(
        {
            "birth_date": {
                "value": "1957-01-15",
                "derivation": {
                    "method": "fi-hetu",
                    "source_path": "patient.identifiers[0]",
                    "recognised_by": "label",
                },
            }
        }
    )
    flag = ReviewFlag(path="patient.birth_date", reason=ReviewReason.DERIVED_FROM_IDENTITY_CODE)
    return DeriveOutcome(enriched.model_copy(update={"patient_derived": derived}), (flag,))


def test_derived_birth_date_must_be_confirmed() -> None:
    services = make_services(hooks=PipelineHooks(derive=_derive_birth_date))
    with _client(services) as client:
        job_id = _job_id(client, CSV_CASE)
        draft = _draft(client, job_id)
        birth = draft["patient"]["birth_date"]
        assert birth["derived"]["value"] == "1957-01-15"
        assert "derived_from_identity_code" in birth["flags"]
        assert birth["source"]["quote"]  # quoted where the identity code is
        assert [b["code"] for b in draft["blockers"]] == ["derived_value_unconfirmed"]
        assert _approve(client, job_id, 1).status_code == 409
        assert (
            _put(
                client,
                job_id,
                1,
                {"action": "edit", "path": "patient.birth_date", "value": {"value": "1960"}},
            ).json()["error"]["code"]
            == "derived_not_editable"
        )
        draft = _put(client, job_id, 1, {"action": "confirm", "path": "patient.birth_date"}).json()
        assert draft["blockers"] == []
        assert draft["patient"]["birth_date"]["confirmed"] is True
        approval = _approve(client, job_id, 2)
        assert approval.status_code == 200, approval.text
        bundle = client.get(f"/api/jobs/{job_id}/ips").json()
        patient = next(
            e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient"
        )
        assert patient["birthDate"] == "1957-01-15"


def _validator(issues: list[ValidationIssue]) -> Any:
    def validate(bundle: Bundle) -> ValidationResult:
        return ValidationResult(profile="test", issues=tuple(issues))

    return validate


def test_approval_requires_passing_validation() -> None:
    error = ValidationIssue(
        severity="error",
        code="invariant",
        message="Patient Aino broke a rule",
        expression=("Bundle.entry[1]",),
    )
    services = make_services(validator=_validator([error]))
    with _client(services) as client:
        job_id = _job_id(client, TXT_CASE)
        draft = _draft(client, job_id)
        assert draft["validation"]["passed"] is False
        response = _approve(client, job_id, 1)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"
        assert "Aino" not in response.text  # issue messages are never returned
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "review"


def test_validator_unavailable_does_not_approve() -> None:
    calls = {"n": 0}

    def flaky(bundle: Bundle) -> ValidationResult:
        calls["n"] += 1
        if calls["n"] > 1:
            raise MatchboxError("down")
        return ValidationResult(profile="test")

    services = make_services(validator=flaky)
    with _client(services) as client:
        job_id = _job_id(client, TXT_CASE)
        assert _draft(client, job_id)["validation"]["passed"] is True
        assert _approve(client, job_id, 1).json()["error"]["code"] == "validator_unavailable"


# ---- configuration --------------------------------------------------------------------------


def test_api_refuses_to_start_outside_development() -> None:
    with pytest.raises(ConfigError, match="authentication"):
        create_app(settings=Settings(app_env="production"))
    with pytest.raises(ConfigError, match="not implemented"):
        create_app(settings=Settings(app_env="development", auth_mode="oidc"))  # type: ignore[arg-type]


def test_replay_refused_outside_development() -> None:
    from app.pipeline.extractors import ExtractorConfigError, build_extractor

    settings = Settings(
        app_env="staging", extractor=ExtractorKind.REPLAY, replay_dataset_dir=DATASET
    )
    with pytest.raises(ExtractorConfigError, match="APP_ENV=development"):
        build_extractor(settings)
