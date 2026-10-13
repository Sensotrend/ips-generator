"""Wallet export: the API asks the credential issuer for an offer URL (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import Services
from tests.api_support import dataset_document, make_services

OFFER = "openid-credential-offer://?credential_offer_uri=https%3A%2F%2Fissuer.example%2Foffer%2F1"


def _services(handler: Callable[[httpx.Request], httpx.Response]) -> Services:
    services = make_services()
    services.wallet_transport = httpx.MockTransport(handler)
    return services


def _upload(client: TestClient) -> str:
    path = dataset_document("fi01_discharge_internal_txt")
    files = {"file": (path.name, path.read_bytes(), "application/octet-stream")}
    return str(client.post("/api/jobs", files=files).json()["id"])


def _approved_job(client: TestClient) -> str:
    job_id = _upload(client)
    approval = client.post(f"/api/jobs/{job_id}/approve", json={"version": 1, "role": "clinician"})
    assert approval.is_success, approval.text
    return job_id


def test_wallet_offer_posts_bundle_and_returns_url() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"url": OFFER})

    with TestClient(create_app(_services(handler))) as client:
        job_id = _approved_job(client)
        response = client.post(f"/api/jobs/{job_id}/wallet-offer")
        bundle = client.get(f"/api/jobs/{job_id}/ips").json()
    assert response.status_code == 200
    assert response.json() == {"url": OFFER}
    assert seen[0]["protocol"] == "OPENID4VCI_FINAL1"
    assert json.loads(seen[0]["content"]) == bundle  # the issuer wants the Bundle as a string


def test_wallet_offer_requires_approval() -> None:
    services = _services(lambda request: httpx.Response(200, json={"url": OFFER}))
    with TestClient(create_app(services)) as client:
        response = client.post(f"/api/jobs/{_upload(client)}/wallet-offer")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_approved"


def test_wallet_offer_issuer_error_is_502() -> None:
    services = _services(lambda request: httpx.Response(500, json={"error": "boom"}))
    with TestClient(create_app(services)) as client:
        response = client.post(f"/api/jobs/{_approved_job(client)}/wallet-offer")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "wallet_failed"


def test_wallet_offer_unreachable_is_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with TestClient(create_app(_services(handler))) as client:
        assert client.post(f"/api/jobs/{_approved_job(client)}/wallet-offer").status_code == 502
