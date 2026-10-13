"""Matchbox $validate client, with a mocked HTTP transport (no network)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.fhir.constants import PROFILE_BUNDLE_VERSIONED
from app.fhir.models import Bundle
from app.pipeline.validate import (
    MatchboxClient,
    MatchboxError,
    ValidationResult,
    parse_operation_outcome,
)

BASE_URL = "http://matchbox.test/matchboxv3/fhir"
MINIMAL = Path(__file__).parents[1] / "fixtures" / "ips-examples" / "Bundle-bundle-minimal.json"

OUTCOME: dict[str, Any] = {
    "resourceType": "OperationOutcome",
    "issue": [
        {
            "severity": "information",
            "code": "informational",
            "diagnostics": "Validation for profile ...",
        },
        {
            "extension": [
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-issue-source",
                    "valueString": "InstanceValidator",
                },
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-message-id",
                    "valueCode": "Bundle_BUNDLE_Entry_NoFirst",
                },
            ],
            "severity": "error",
            "code": "invalid",
            "diagnostics": "Documents or Messages must contain at least one entry",
            "expression": ["Bundle"],
        },
        {
            "severity": "warning",
            "code": "code-invalid",
            "details": {"text": "None of the codings provided are in the value set"},
            "location": ["Bundle.entry[1].resource.contact[0]"],
        },
        {
            "severity": "information",
            "code": "informational",
            "diagnostics": "This element does not match any known slice defined in the profile",
            "expression": ["Bundle.entry[5]"],
        },
        {"severity": "fatal", "code": "invalid", "diagnostics": "Error parsing JSON"},
    ],
}


def _client(handler: Any) -> MatchboxClient:
    return MatchboxClient(
        BASE_URL, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_posts_bundle_to_validate_with_profile() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"resourceType": "OperationOutcome", "issue": []})

    raw = json.loads(MINIMAL.read_text(encoding="utf-8"))
    with _client(handler) as client:
        result = client.validate(Bundle.model_validate(raw))

    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/matchboxv3/fhir/$validate"
    assert request.url.params["profile"] == PROFILE_BUNDLE_VERSIONED
    assert request.headers["content-type"] == "application/fhir+json"
    assert json.loads(request.content) == raw
    assert result.is_valid
    assert result.issues == ()


def test_accepts_plain_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"resourceType": "Bundle", "type": "document"}
        return httpx.Response(200, json=OUTCOME)

    result = _client(handler).validate({"resourceType": "Bundle", "type": "document"})
    assert not result.is_valid


def test_parses_issues() -> None:
    result = parse_operation_outcome(OUTCOME, profile="p")
    assert isinstance(result, ValidationResult)
    assert result.counts() == {"fatal": 1, "error": 1, "warning": 1, "information": 2}
    assert [i.severity for i in result.errors] == ["error", "fatal"]
    assert len(result.warnings) == 1
    assert not result.is_valid

    error = result.errors[0]
    assert error.code == "invalid"
    assert error.path == "Bundle"
    assert error.message_id == "Bundle_BUNDLE_Entry_NoFirst"
    assert error.source == "InstanceValidator"

    warning = result.warnings[0]
    assert warning.message == "None of the codings provided are in the value set"
    assert warning.path == "Bundle.entry[1].resource.contact[0]"
    assert result.unmatched_bundle_entries == [5]


def test_valid_when_only_warnings() -> None:
    outcome = {"resourceType": "OperationOutcome", "issue": OUTCOME["issue"][2:4]}
    result = parse_operation_outcome(outcome, profile="p")
    assert result.is_valid
    assert result.errors == []


def test_non_2xx_operation_outcome_is_still_a_result() -> None:
    result = _client(lambda _r: httpx.Response(422, json=OUTCOME)).validate({})
    assert len(result.errors) == 2


def test_validator_setup_problem_raises() -> None:
    outcome = {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "extension": [
                    {
                        "url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-issue-source",
                        "valueString": "ValidationProvider",
                    }
                ],
                "severity": "error",
                "code": "exception",
                "diagnostics": "Matchbox engine for profile 'x' could not be created",
            }
        ],
    }
    with pytest.raises(MatchboxError, match="could not be created"):
        _client(lambda _r: httpx.Response(200, json=outcome)).validate({})


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="Bad gateway"),
        httpx.Response(200, json={"resourceType": "Bundle"}),
        httpx.Response(200, json=[1, 2]),
    ],
)
def test_bad_responses_raise(response: httpx.Response) -> None:
    with pytest.raises(MatchboxError):
        _client(lambda _r: response).validate({})


def test_transport_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(MatchboxError, match="ConnectError"):
        _client(handler).validate({})


def test_base_url_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("MATCHBOX_URL", "http://configured:1234/fhir/")
    get_settings.cache_clear()
    try:
        client = MatchboxClient()
        assert client.base_url == "http://configured:1234/fhir"
        client.close()
    finally:
        get_settings.cache_clear()
