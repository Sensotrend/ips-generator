"""Approve eval documents through the API and validate the attested Bundle in Matchbox.

Skipped when Matchbox is unreachable (``docker compose -f infra/docker-compose.yml up -d``).
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.fhir.models import Bundle
from app.main import create_app
from app.pipeline.validate import MatchboxClient, ValidationResult
from tests.api_support import dataset_document, make_services

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def matchbox() -> Iterator[MatchboxClient]:
    base_url = get_settings().matchbox_url.rstrip("/")
    try:
        httpx.get(f"{base_url}/metadata", timeout=5.0).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Matchbox not reachable at {base_url}")
    with MatchboxClient(base_url) as client:
        yield client


@pytest.mark.parametrize(
    ("case_id", "role"),
    [("fi01_discharge_internal_txt", "clinician"), ("en01_discharge_resp_pdf", "patient")],
)
def test_approved_bundle_validates(matchbox: MatchboxClient, case_id: str, role: str) -> None:
    def validate(bundle: Bundle) -> ValidationResult:
        return matchbox.validate(bundle)

    services = make_services(validator=validate)
    with TestClient(create_app(services)) as client:
        path = dataset_document(case_id)
        job = client.post("/api/jobs", files={"file": (path.name, path.read_bytes())}).json()
        assert job["status"] == "review", job
        approval = client.post(f"/api/jobs/{job['id']}/approve", json={"version": 1, "role": role})
        assert approval.status_code == 200, approval.text
        validation = approval.json()["validation"]
        assert validation["errors"] == 0
        assert validation["unmatched_entries"] == []
