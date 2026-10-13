"""Fakes for terminology tests: an in-process FHIR terminology server and a scripted Claude.

Both record every request so tests can inspect exactly what would leave the process.
Synthetic data only.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import anthropic
import httpx
import httpx2
from pydantic import SecretStr

from app.config import LlmProvider, Settings
from app.fhir.constants import SNOMED_CT
from app.llm.client import LlmClient, create_client
from app.terminology.client import TerminologyClient
from app.terminology.scopes import ATC, EDQM, ICD_10, SCOPES, SearchScope

SCT_VERSION = "http://snomed.info/sct/900000000000207008/version/20250201"
FSN = "900000000000003001"
SYNONYM = "900000000000013009"


@dataclass(frozen=True)
class FakeConcept:
    system: str
    code: str
    display: str
    scopes: frozenset[SearchScope] = frozenset()
    synonyms: tuple[str, ...] = ()
    fsn: str | None = None
    inactive: bool = False


def sct(code: str, display: str, *scopes: SearchScope, synonyms: Iterable[str] = ()) -> FakeConcept:
    return FakeConcept(
        SNOMED_CT, code, display, frozenset(scopes), tuple(synonyms), fsn=f"{display} (finding)"
    )


DEFAULT_CONCEPTS: tuple[FakeConcept, ...] = (
    sct("44054006", "Type 2 diabetes mellitus", SearchScope.PROBLEM),
    sct("81531005", "Type 2 diabetes mellitus in obese", SearchScope.PROBLEM),
    sct("195967001", "Asthma", SearchScope.PROBLEM, SearchScope.CLINICAL_FINDING),
    sct("762952008", "Peanut", SearchScope.ALLERGY_SUBSTANCE),
    sct("91935009", "Allergy to peanut", SearchScope.ALLERGY_SUBSTANCE),
    sct("126485001", "Urticaria", SearchScope.CLINICAL_FINDING, synonyms=["Hives"]),
    sct("267038008", "Edema", SearchScope.CLINICAL_FINDING, synonyms=["Oedema"]),
    sct("776713006", "Metformin only product", SearchScope.MEDICINAL_PRODUCT),
    sct("109081006", "Metformin-containing product", SearchScope.MEDICINAL_PRODUCT),
    sct("26643006", "Oral route", SearchScope.ROUTE),
    sct("255604002", "Mild", SearchScope.SEVERITY),
    sct("6736007", "Moderate severity", SearchScope.SEVERITY),
    sct("24484000", "Severe", SearchScope.SEVERITY),
    sct("82169009", "Structure of left knee region", SearchScope.BODY_STRUCTURE),
    FakeConcept(ATC, "A10BA02", "metformin", frozenset({SearchScope.ATC})),
    FakeConcept(ATC, "C09AA05", "ramipril", frozenset({SearchScope.ATC})),
    FakeConcept(EDQM, "10219000", "Tablet", frozenset({SearchScope.DOSE_FORM})),
    FakeConcept(ICD_10, "E11.9", "Type 2 diabetes mellitus : Without complications"),
    FakeConcept(ICD_10, "E11", "Type 2 diabetes mellitus"),
)


def _scope_of_url(url: str) -> SearchScope | None:
    for scope, definition in SCOPES.items():
        if definition.url == url:
            return scope
    return None


def _scope_of_compose(compose: Any) -> SearchScope | None:
    for scope, definition in SCOPES.items():
        if definition.compose is not None and definition.compose == compose:
            return scope
    return None


@dataclass
class FakeTxServer:
    """Answers ``$expand`` (word filter over displays/synonyms) and ``$lookup``."""

    concepts: tuple[FakeConcept, ...] = DEFAULT_CONCEPTS
    requests: list[httpx.Request] = field(default_factory=list)
    fail_with: list[int] = field(default_factory=list)
    """Status codes to answer with before behaving normally (e.g. [503])."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_with:
            return httpx.Response(self.fail_with.pop(0), json={"resourceType": "OperationOutcome"})
        path = urlsplit(str(request.url)).path
        params = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        if path.endswith("/ValueSet/$expand"):
            if request.method == "POST":
                body = json.loads(request.content)
                values = {p["name"]: p for p in body["parameter"]}
                scope = _scope_of_compose(values["valueSet"]["resource"]["compose"])
                text = values["filter"]["valueString"]
                count = values["count"]["valueInteger"]
                designations = "includeDesignations" in values
            else:
                scope = _scope_of_url(params["url"])
                text, count = params["filter"], int(params["count"])
                designations = params.get("includeDesignations") == "true"
            if scope is None:
                return _outcome(422, "ValueSet not found")
            return httpx.Response(200, json=self._expand(scope, text, count, designations))
        if path.endswith("/CodeSystem/$lookup"):
            for c in self.concepts:
                if c.system == params["system"] and c.code == params["code"]:
                    return httpx.Response(200, json=_lookup_body(c))
            return _outcome(404, "Unable to find code")
        return _outcome(400, "unsupported")

    def _expand(self, scope: SearchScope, text: str, count: int, designations: bool) -> Any:
        words = text.lower().split()
        hits = [
            c
            for c in self.concepts
            if scope in c.scopes
            and all(any(w in t.lower() for t in (c.display, *c.synonyms)) for w in words)
        ][:count]
        contains = []
        for c in hits:
            entry: dict[str, Any] = {"system": c.system, "code": c.code, "display": c.display}
            if c.inactive:
                entry["inactive"] = True
            if designations:
                entry["designation"] = _designations(c)
            contains.append(entry)
        system = SCOPES[scope].system
        version = SCT_VERSION if system == SNOMED_CT else "2025"
        return {
            "resourceType": "ValueSet",
            "expansion": {
                "parameter": [{"name": "used-codesystem", "valueUri": f"{system}|{version}"}],
                "contains": contains,
            },
        }

    def bodies(self) -> list[str]:
        """Every request as text (URL + body), for privacy assertions."""
        return [f"{r.url} {r.content.decode('utf-8', 'replace')}" for r in self.requests]

    def client(self, **kwargs: Any) -> TerminologyClient:
        kwargs.setdefault("min_interval_s", 0.0)
        kwargs.setdefault("sleep", lambda _s: None)
        return TerminologyClient(
            "https://tx.example.org/r4", transport=httpx.MockTransport(self), **kwargs
        )


def _designations(c: FakeConcept) -> list[dict[str, Any]]:
    result = [{"language": "en", "use": {"code": SYNONYM}, "value": c.display}]
    result += [{"language": "en", "use": {"code": SYNONYM}, "value": s} for s in c.synonyms]
    if c.fsn:
        result.append({"language": "en", "use": {"code": FSN}, "value": c.fsn})
    return result


def _lookup_body(c: FakeConcept) -> dict[str, Any]:
    version = SCT_VERSION if c.system == SNOMED_CT else "2025"
    parameters: list[dict[str, Any]] = [
        {"name": "name", "valueString": "fake"},
        {"name": "system", "valueUri": c.system},
        {"name": "version", "valueString": version},
        {"name": "display", "valueString": c.display},
        {
            "name": "property",
            "part": [
                {"name": "code", "valueCode": "inactive"},
                {"name": "value", "valueBoolean": c.inactive},
            ],
        },
    ]
    for d in _designations(c):
        parameters.append(
            {
                "name": "designation",
                "part": [
                    {"name": "language", "valueCode": d["language"]},
                    {"name": "use", "valueCoding": {"code": d["use"]["code"]}},
                    {"name": "value", "valueString": d["value"]},
                ],
            }
        )
    return {"resourceType": "Parameters", "parameter": parameters}


def _outcome(status: int, text: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "not-found", "details": {"text": text}}],
        },
    )


# --------------------------------------------------------------------------------------------
# Scripted Claude (non-streaming Messages API)
# --------------------------------------------------------------------------------------------

MODEL = "claude-sonnet-5-5"


def message(
    *blocks: dict[str, Any],
    stop_reason: str = "end_turn",
    model: str = MODEL,
    stop_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, *blocks],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1500,
        },
    }


_tool_ids = iter(range(1, 10_000))


def tool_use(name: str, **tool_input: Any) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": f"toolu_{next(_tool_ids):04d}",
        "name": name,
        "input": tool_input,
    }


def tool_turn(*uses: dict[str, Any]) -> dict[str, Any]:
    return message(*uses, stop_reason="tool_use")


def answer(*codes: tuple[str, str, str]) -> dict[str, Any]:
    payload = {"codes": [{"field_id": f, "system": s, "code": c} for f, s, c in codes]}
    return message({"type": "text", "text": json.dumps(payload)})


class FakeClaude:
    """Answers each request with the next scripted message (or a callable producing one)."""

    def __init__(self, *responses: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]):
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        response = self.responses.pop(0)
        body = response(self.body(len(self.requests) - 1)) if callable(response) else response
        return httpx2.Response(
            200,
            headers={"request-id": f"req_{len(self.requests)}"},
            json=body,
        )

    def body(self, index: int) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[index].content)
        return body

    def client(self, provider: LlmProvider = LlmProvider.ANTHROPIC) -> LlmClient:
        """A client built like production (`create_client`, incl. its SDK logging guard)."""
        http = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self))
        settings = Settings(anthropic_api_key=SecretStr("test-key"))
        client = create_client(settings, max_retries=0, http_client=http)
        return LlmClient(provider=provider, sdk=client.sdk)
