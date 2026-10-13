"""Tests for the FHIR terminology client and search scopes (no network: httpx.MockTransport)."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.fhir.constants import SNOMED_CT
from app.terminology.client import (
    QueryRejectedError,
    TerminologyClient,
    TerminologyError,
    check_query_text,
)
from app.terminology.scopes import (
    ATC,
    ICD_10,
    SCOPES,
    SearchScope,
    infer_printed_system,
    normalise_printed_code,
    system_from_text,
)
from tests.terminology_fakes import SCT_VERSION, FakeTxServer

# --------------------------------------------------------------------------------------------
# search / lookup
# --------------------------------------------------------------------------------------------


def test_search_by_url_scope_uses_get_and_parses_version() -> None:
    server = FakeTxServer()
    with server.client() as tx:
        result = tx.search(SearchScope.ROUTE, "oral", count=5)
    request = server.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/r4/ValueSet/$expand"
    assert request.url.params["url"] == "http://hl7.org/fhir/ValueSet/route-codes"
    assert request.url.params["filter"] == "oral"
    assert request.url.params["count"] == "5"
    assert request.headers["accept"] == "application/fhir+json"
    assert "ips-generator" in request.headers["user-agent"]
    assert [(c.system, c.code, c.display) for c in result.concepts] == [
        (SNOMED_CT, "26643006", "Oral route")
    ]
    assert result.concepts[0].version == SCT_VERSION


def test_search_by_inline_compose_posts_parameters() -> None:
    server = FakeTxServer()
    with server.client() as tx:
        result = tx.search(SearchScope.PROBLEM, "type 2 diabetes", include_designations=True)
    request = server.requests[0]
    assert request.method == "POST"
    body = json.loads(request.content)
    values = {p["name"]: p for p in body["parameter"]}
    assert values["valueSet"]["resource"]["compose"] == SCOPES[SearchScope.PROBLEM].compose
    assert values["filter"]["valueString"] == "type 2 diabetes"
    assert values["includeDesignations"]["valueBoolean"] is True
    assert result.concepts[0].code == "44054006"
    assert any(d.value == "Type 2 diabetes mellitus" for d in result.concepts[0].designations)


def test_lookup_found_and_not_found() -> None:
    server = FakeTxServer()
    with server.client() as tx:
        found = tx.lookup(ICD_10, "E11.9")
        missing = tx.lookup(ICD_10, "E11.8")
    assert found.concept is not None
    assert found.concept.display == "Type 2 diabetes mellitus : Without complications"
    assert found.concept.version == "2025"
    assert missing.concept is None


def test_lookup_rejects_malformed_code_without_request() -> None:
    server = FakeTxServer()
    with server.client() as tx, pytest.raises(QueryRejectedError):
        tx.lookup(ATC, "metformin")
    assert server.requests == []


def test_validate_code_and_subsumes_parse_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("$validate-code"):
            return httpx.Response(
                200,
                json={
                    "resourceType": "Parameters",
                    "parameter": [
                        {"name": "result", "valueBoolean": False},
                        {"name": "display", "valueString": "Asthma, unspecified"},
                        {"name": "message", "valueString": "Wrong Display Name"},
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "resourceType": "Parameters",
                "parameter": [{"name": "outcome", "valueCode": "subsumes"}],
            },
        )

    with TerminologyClient(
        "https://tx.example.org/r4", transport=httpx.MockTransport(handler), min_interval_s=0
    ) as tx:
        validated = tx.validate_code(ICD_10, "J45.9", display="Asthma")
        assert validated.result is False
        assert validated.display == "Asthma, unspecified"
        assert tx.subsumes(SNOMED_CT, "404684003", "44054006") == "subsumes"


# --------------------------------------------------------------------------------------------
# retries, rate limiting, cache
# --------------------------------------------------------------------------------------------


def test_retries_5xx_then_succeeds_with_backoff() -> None:
    server = FakeTxServer(fail_with=[503, 502])
    sleeps: list[float] = []
    with server.client(sleep=sleeps.append, max_retries=2) as tx:
        result = tx.lookup(ATC, "A10BA02")
    assert result.concept is not None
    assert len(server.requests) == 3
    assert sleeps == [0.5, 1.0]
    assert tx.stats.retries == 2


def test_gives_up_after_max_retries() -> None:
    server = FakeTxServer(fail_with=[500, 500, 500])
    with server.client(max_retries=2) as tx, pytest.raises(TerminologyError, match="HTTP 500"):
        tx.lookup(ATC, "A10BA02")
    assert len(server.requests) == 3


def test_429_honours_retry_after() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return FakeTxServer()(request)

    sleeps: list[float] = []
    with TerminologyClient(
        "https://tx.example.org/r4",
        transport=httpx.MockTransport(handler),
        min_interval_s=0,
        sleep=sleeps.append,
    ) as tx:
        tx.lookup(ATC, "A10BA02")
    assert sleeps == [3.0]


def test_4xx_is_not_retried() -> None:
    server = FakeTxServer(fail_with=[400])
    with server.client() as tx, pytest.raises(TerminologyError, match="HTTP 400"):
        tx.search(SearchScope.ROUTE, "oral")
    assert len(server.requests) == 1


def test_transport_errors_are_retried_then_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with (
        TerminologyClient(
            "https://tx.example.org/r4",
            transport=httpx.MockTransport(handler),
            min_interval_s=0,
            max_retries=1,
            sleep=lambda _s: None,
        ) as tx,
        pytest.raises(TerminologyError, match="ConnectError"),
    ):
        tx.lookup(ATC, "A10BA02")


def test_minimum_interval_between_requests() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    server = FakeTxServer()
    with server.client(min_interval_s=0.25, sleep=sleep, clock=lambda: now[0]) as tx:
        tx.lookup(ATC, "A10BA02")
        now[0] += 0.05
        tx.lookup(ATC, "C09AA05")
    assert sleeps == [pytest.approx(0.2)]


def test_cache_answers_repeated_requests_including_not_found() -> None:
    server = FakeTxServer()
    with server.client() as tx:
        first = tx.search(SearchScope.PROBLEM, "asthma")
        second = tx.search(SearchScope.PROBLEM, "asthma")
        tx.lookup(ICD_10, "Z99.9")
        assert tx.lookup(ICD_10, "Z99.9").concept is None
        tx.search(SearchScope.PROBLEM, "asthma", count=3)  # different request: not cached
    assert first == second
    assert len(server.requests) == 3
    assert tx.stats.cache_hits == 2


def test_cache_is_lru_bounded() -> None:
    server = FakeTxServer()
    with server.client(cache_size=1) as tx:
        tx.lookup(ATC, "A10BA02")
        tx.lookup(ATC, "C09AA05")
        tx.lookup(ATC, "A10BA02")
    assert len(server.requests) == 3


# --------------------------------------------------------------------------------------------
# privacy guard and logging
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "150372-9477",  # Finnish personal identity code
        "Virtanen 150372-9477",
        "diabetes 12.03.2018",
        "2018-03-12",
        "potilas 1234567",
        "matti@example.org",
        "x" * 101,
        "line one\nline two",
        "   ",
    ],
)
def test_query_guard_rejects_identifiers_dates_and_notes(text: str) -> None:
    server = FakeTxServer()
    with pytest.raises(QueryRejectedError) as excinfo:
        check_query_text(text)
    assert text.strip() == "" or text not in str(excinfo.value)
    with server.client() as tx, pytest.raises(QueryRejectedError):
        tx.search(SearchScope.PROBLEM, text)
    assert server.requests == []


@pytest.mark.parametrize("text", ["Type 2 diabetes mellitus", "Peanut", "oral", "Vitamin B12"])
def test_query_guard_accepts_clinical_terms(text: str) -> None:
    assert check_query_text(f"  {text} ") == text


def test_logs_contain_no_query_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    server = FakeTxServer(fail_with=[503])
    with server.client() as tx:
        tx.search(SearchScope.PROBLEM, "Type 2 diabetes mellitus")
    assert "status=503" in caplog.text
    assert "diabetes" not in caplog.text.lower()


# --------------------------------------------------------------------------------------------
# scopes / printed codes
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("ICD-10", ICD_10),
        ("icd10", ICD_10),
        ("ICD-10-koodi", ICD_10),
        ("ATC", ATC),
        ("atc", ATC),
        ("ATC-koodi", ATC),
        ("SNOMED CT", SNOMED_CT),
        ("ICD-10-CM", None),
        ("ICPC-2", None),
        ("", None),
        (None, None),
    ],
)
def test_system_from_text(label: str | None, expected: str | None) -> None:
    assert system_from_text(label) == expected


@pytest.mark.parametrize(
    ("code", "system", "expected"),
    [
        ("E11.9", ICD_10, "E11.9"),
        ("e119", ICD_10, "E11.9"),
        ("E10.5†", ICD_10, "E10.5"),
        ("H36.0*", ICD_10, "H36.0"),
        ("E11.999", ICD_10, None),
        (" A10BA02 ", ATC, "A10BA02"),
        ("A10BA0", ATC, None),
        ("44054006", SNOMED_CT, "44054006"),
        ("0123", SNOMED_CT, None),
    ],
)
def test_normalise_printed_code(code: str, system: str, expected: str | None) -> None:
    assert normalise_printed_code(code, system) == expected


@pytest.mark.parametrize(
    ("code", "kind", "expected"),
    [
        ("A10BA02", "condition", ATC),
        ("A10BA02", "allergy", ATC),
        ("A10BA", "medication", ATC),
        ("E11.9", "condition", ICD_10),
        ("J01", "medication", None),  # ambiguous: ATC group or ICD-10 category
        ("J01", "allergy", None),
        ("E11.9", "medication", None),
    ],
)
def test_infer_printed_system(code: str, kind: str, expected: str | None) -> None:
    assert infer_printed_system(code, item_kind=kind) == expected
