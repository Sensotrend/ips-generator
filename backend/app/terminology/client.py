"""Typed FHIR R4 terminology client (``$expand``, ``$lookup``, ``$validate-code``, ``$subsumes``).

Synchronous like `app.pipeline.validate` (the pipeline runs in RQ worker jobs). Server findings
and the search scopes are documented in `app.terminology.scopes`.

Behaviour
---------
* **Timeouts and retries:** connection errors, timeouts, 429 and 5xx are retried with
  exponential backoff (``Retry-After`` honoured, capped); other 4xx are not.
* **Politeness:** one request at a time per client with a minimum interval between requests,
  and a User-Agent naming the project (tx.fhir.org is a shared test server).
* **Cache:** an in-memory LRU of parsed answers keyed by the exact request. "Not found" lookups
  are cached too; errors are not. There is deliberately no disk cache: query text comes from
  documents, and persisting it would need the PHI handling of the audit store (PLAN §7).

Privacy (CLAUDE.md)
-------------------
Only clinical term text and codes may be sent. The coder (`app.pipeline.terminology`) passes
only the items' codable term fields, which is the structural guarantee; this client adds a
defensive check (`check_query_text`) that rejects text that looks like an identifier, a date or
a long free-text note before anything is sent, and codes must match their system's syntax.
Nothing here logs query text, codes or response content: only operation, status, latency and
cache hits.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Final, Self

import httpx

from app.config import Settings, get_settings
from app.terminology.scopes import CODE_PATTERNS, SearchScope

logger = logging.getLogger(__name__)

__all__ = [
    "Concept",
    "ConceptNotFoundError",
    "Designation",
    "LookupResult",
    "QueryRejectedError",
    "SearchResult",
    "TerminologyClient",
    "TerminologyError",
    "ValidateCodeResult",
    "check_query_text",
]

USER_AGENT: Final = "ips-generator/0.1 (development; terminology client)"
MAX_QUERY_CHARS: Final = 100
MAX_RETRY_AFTER_S: Final = 10.0

_HETU_RE = re.compile(r"\d{6}[-+A-FU-Y]\d{3}[0-9A-Y]", re.IGNORECASE)
_DATE_RE = re.compile(r"\d{1,4}\s?[./-]\s?\d{1,2}\s?[./-]\s?\d{1,4}")
_LONG_NUMBER_RE = re.compile(r"\d{5,}")
_CONTACT_RE = re.compile(r"@|https?://|www\.", re.IGNORECASE)


class TerminologyError(RuntimeError):
    """The server could not answer (unreachable, 5xx after retries, unexpected response).

    Messages contain the operation and status only, never query text."""


class ConceptNotFoundError(TerminologyError):
    """Raised by callers that require a code to exist (the client returns ``None`` instead)."""


class QueryRejectedError(ValueError):
    """Text or code refused before sending (privacy guard or code syntax). No text in message."""


def check_query_text(text: str) -> str:
    """Return the stripped search text, or raise `QueryRejectedError`.

    Defence in depth: the coder only ever passes clinical term fields, but text that looks like
    a personal identity code, a date, a long number, contact data or a free-text note (too long,
    several lines) is never sent to an external server.
    """
    stripped = " ".join(text.split())
    if not stripped:
        raise QueryRejectedError("empty search text")
    if len(stripped) > MAX_QUERY_CHARS or "\n" in text.strip():
        raise QueryRejectedError("search text too long for a clinical term")
    if _HETU_RE.search(stripped) or _LONG_NUMBER_RE.search(stripped):
        raise QueryRejectedError("search text contains an identifier-like number")
    if _DATE_RE.search(stripped):
        raise QueryRejectedError("search text contains a date")
    if _CONTACT_RE.search(stripped):
        raise QueryRejectedError("search text contains contact data")
    return stripped


def check_code(system: str, code: str) -> str:
    pattern = CODE_PATTERNS.get(system)
    if pattern is None:
        raise QueryRejectedError("unsupported code system for lookup")
    if not pattern.fullmatch(code):
        raise QueryRejectedError("code does not match the system's syntax")
    return code


# --------------------------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Designation:
    value: str
    language: str | None = None
    use: str | None = None
    """``use`` code, e.g. SNOMED 900000000000013009 (synonym) / 900000000000003001 (FSN)."""


@dataclass(frozen=True, slots=True)
class Concept:
    """One concept returned by the server. ``display`` is the server's display (English)."""

    system: str
    code: str
    display: str
    version: str | None = None
    designations: tuple[Designation, ...] = ()
    inactive: bool = False


@dataclass(frozen=True, slots=True)
class SearchResult:
    operation: str
    concepts: tuple[Concept, ...]
    total: int | None


@dataclass(frozen=True, slots=True)
class LookupResult:
    operation: str
    concept: Concept | None
    """``None``: the code does not exist in the system (HTTP 404)."""


@dataclass(frozen=True, slots=True)
class ValidateCodeResult:
    result: bool
    display: str | None
    message: str | None = field(default=None, repr=False)
    """Server message; may quote the display that was sent. Never log it."""


@dataclass
class ClientStats:
    requests: int = 0
    cache_hits: int = 0
    retries: int = 0
    errors: int = 0


# --------------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------------


OP_EXPAND: Final = "ValueSet/$expand"
OP_LOOKUP: Final = "CodeSystem/$lookup"
OP_VALIDATE: Final = "CodeSystem/$validate-code"
OP_SUBSUMES: Final = "CodeSystem/$subsumes"


class TerminologyClient:
    """FHIR terminology client. Use as a context manager or call `close()`.

    ``transport`` is for tests (``httpx.MockTransport``); ``sleep``/``clock`` make the rate
    limiter and backoff testable.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        settings: Settings | None = None,
        timeout_s: float | None = None,
        max_retries: int | None = None,
        min_interval_s: float | None = None,
        cache_size: int | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = settings or get_settings()
        self.base_url = (base_url or settings.terminology_server_url).rstrip("/")
        self.max_retries = settings.terminology_max_retries if max_retries is None else max_retries
        self.min_interval_s = (
            settings.terminology_min_interval_s if min_interval_s is None else min_interval_s
        )
        self._cache_size = settings.terminology_cache_size if cache_size is None else cache_size
        self._cache: OrderedDict[str, object] = OrderedDict()
        self._lock = threading.Lock()
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.stats = ClientStats()
        _guard_httpx_logging()
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=settings.terminology_timeout_s if timeout_s is None else timeout_s,
            headers={"Accept": "application/fhir+json", "User-Agent": USER_AGENT},
            transport=transport,
        )

    # -- lifecycle --------------------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- operations ---------------------------------------------------------------------------

    def search(
        self,
        scope: SearchScope | str,
        text: str,
        *,
        count: int = 10,
        include_designations: bool = False,
    ) -> SearchResult:
        """``ValueSet/$expand`` with ``filter=text`` over ``scope`` (a `SearchScope` or a value
        set canonical URL the server knows)."""
        query = check_query_text(text)
        count = max(1, min(count, 50))
        url: str | None
        compose: dict[str, Any] | None
        if isinstance(scope, SearchScope):
            definition = scope.definition
            url, compose = definition.url, definition.compose
        else:
            url, compose = scope, None
        if url is not None:
            params: dict[str, str] = {"url": url, "filter": query, "count": str(count)}
            if include_designations:
                params["includeDesignations"] = "true"
            data = self._request("GET", OP_EXPAND, params=params)
        else:
            parameters: list[dict[str, Any]] = [
                {
                    "name": "valueSet",
                    "resource": {
                        "resourceType": "ValueSet",
                        "status": "active",
                        "compose": compose,
                    },
                },
                {"name": "filter", "valueString": query},
                {"name": "count", "valueInteger": count},
            ]
            if include_designations:
                parameters.append({"name": "includeDesignations", "valueBoolean": True})
            data = self._request(
                "POST", OP_EXPAND, body={"resourceType": "Parameters", "parameter": parameters}
            )
        if data is None or data.get("resourceType") != "ValueSet":
            raise TerminologyError(f"{OP_EXPAND}: unexpected response")
        return _parse_expansion(data)

    def lookup(self, system: str, code: str) -> LookupResult:
        """``CodeSystem/$lookup``; ``concept`` is ``None`` when the code does not exist."""
        check_code(system, code)
        data = self._request(
            "GET", OP_LOOKUP, params={"system": system, "code": code}, not_found_ok=True
        )
        if data is None:
            return LookupResult(operation=OP_LOOKUP, concept=None)
        if data.get("resourceType") != "Parameters":
            raise TerminologyError(f"{OP_LOOKUP}: unexpected response")
        return LookupResult(operation=OP_LOOKUP, concept=_parse_lookup(data, system, code))

    def validate_code(
        self, system: str, code: str, display: str | None = None
    ) -> ValidateCodeResult:
        """``CodeSystem/$validate-code``; with ``display``, ``result`` also checks the display."""
        check_code(system, code)
        params = {"url": system, "code": code}
        if display is not None:
            params["display"] = check_query_text(display)
        data = self._request("GET", OP_VALIDATE, params=params)
        if data is None or data.get("resourceType") != "Parameters":
            raise TerminologyError(f"{OP_VALIDATE}: unexpected response")
        values = _parameter_values(data)
        return ValidateCodeResult(
            result=bool(values.get("result", False)),
            display=_as_str(values.get("display")),
            message=_as_str(values.get("message")),
        )

    def subsumes(self, system: str, code_a: str, code_b: str) -> str:
        """``CodeSystem/$subsumes``: ``equivalent``, ``subsumes``, ``subsumed-by``,
        ``not-subsumed``."""
        check_code(system, code_a)
        check_code(system, code_b)
        data = self._request(
            "GET", OP_SUBSUMES, params={"system": system, "codeA": code_a, "codeB": code_b}
        )
        outcome = _as_str(_parameter_values(data or {}).get("outcome"))
        if outcome is None:
            raise TerminologyError(f"{OP_SUBSUMES}: unexpected response")
        return outcome

    # -- transport ----------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        operation: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        not_found_ok: bool = False,
    ) -> dict[str, Any] | None:
        key = json.dumps([method, operation, params, body], sort_keys=True, ensure_ascii=False)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self.stats.cache_hits += 1
                cached = self._cache[key]
                return cached if isinstance(cached, dict) else None
            data = self._send(
                method, operation, params=params, body=body, not_found_ok=not_found_ok
            )
            self._remember(key, _NOT_FOUND if data is None else data)
            return data

    def _send(
        self,
        method: str,
        operation: str,
        *,
        params: Mapping[str, str] | None,
        body: Mapping[str, Any] | None,
        not_found_ok: bool,
    ) -> dict[str, Any] | None:
        attempt = 0
        while True:
            self._wait_turn()
            started = self._clock()
            self.stats.requests += 1
            try:
                response = self._http.request(
                    method,
                    f"/{operation}",
                    params=params,
                    content=json.dumps(body).encode() if body is not None else None,
                    headers={"Content-Type": "application/fhir+json"} if body is not None else None,
                )
            except httpx.TransportError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    self.stats.retries += 1
                    self._sleep(_backoff(attempt))
                    continue
                self.stats.errors += 1
                logger.warning("terminology %s failed: %s", operation, type(exc).__name__)
                raise TerminologyError(f"{operation}: {type(exc).__name__}") from None
            elapsed_ms = int((self._clock() - started) * 1000)
            status = response.status_code
            logger.info("terminology %s status=%d duration_ms=%d", operation, status, elapsed_ms)
            if status == 429 or status >= 500:
                if attempt < self.max_retries:
                    attempt += 1
                    self.stats.retries += 1
                    self._sleep(_retry_delay(response, attempt))
                    continue
                self.stats.errors += 1
                raise TerminologyError(f"{operation}: HTTP {status}")
            if status == 404 and not_found_ok:
                return None
            if status >= 400:
                self.stats.errors += 1
                raise TerminologyError(f"{operation}: HTTP {status}")
            try:
                data = response.json()
            except ValueError:
                self.stats.errors += 1
                raise TerminologyError(f"{operation}: response is not JSON") from None
            if not isinstance(data, dict):
                raise TerminologyError(f"{operation}: unexpected response")
            return data

    def _wait_turn(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self._last_request + self.min_interval_s - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request = now

    def _remember(self, key: str, value: object) -> None:
        if self._cache_size <= 0:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


_NOT_FOUND: Final = object()


def _guard_httpx_logging() -> None:
    """httpx logs every request URL at INFO, and ``$expand`` GET URLs carry the search text
    (document-derived). Keep the ``httpx`` logger at WARNING or above (CLAUDE.md: never log
    document contents); its INFO lines carry nothing else we need."""
    httpx_logger = logging.getLogger("httpx")
    if httpx_logger.getEffectiveLevel() < logging.WARNING:
        httpx_logger.setLevel(logging.WARNING)


def _backoff(attempt: int) -> float:
    return float(min(0.5 * 2 ** (attempt - 1), MAX_RETRY_AFTER_S))


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After")
    if header is not None:
        try:
            return min(max(float(header), 0.0), MAX_RETRY_AFTER_S)
        except ValueError:
            pass
    return _backoff(attempt)


# --------------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------------


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parameter_values(data: Mapping[str, Any]) -> dict[str, Any]:
    """Top-level ``Parameters.parameter`` values with a ``value[x]`` (first one wins)."""
    values: dict[str, Any] = {}
    for parameter in data.get("parameter", []) or []:
        name = parameter.get("name")
        for key, value in parameter.items():
            if key.startswith("value") and name not in values:
                values[name] = value
    return values


def _parse_expansion(data: Mapping[str, Any]) -> SearchResult:
    expansion = data.get("expansion") or {}
    versions: dict[str, str] = {}
    for parameter in expansion.get("parameter", []) or []:
        if parameter.get("name") == "used-codesystem":
            system, _, version = str(parameter.get("valueUri", "")).partition("|")
            if version:
                versions[system] = version
    concepts: list[Concept] = []

    def walk(entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            system, code, display = entry.get("system"), entry.get("code"), entry.get("display")
            if (
                isinstance(system, str)
                and isinstance(code, str)
                and isinstance(display, str)
                and display.strip()
                and not entry.get("abstract", False)
            ):
                concepts.append(
                    Concept(
                        system=system,
                        code=code,
                        display=display,
                        version=entry.get("version") or versions.get(system),
                        designations=tuple(
                            Designation(
                                value=d["value"],
                                language=d.get("language"),
                                use=(d.get("use") or {}).get("code"),
                            )
                            for d in entry.get("designation", []) or []
                            if isinstance(d.get("value"), str)
                        ),
                        inactive=bool(entry.get("inactive", False)),
                    )
                )
            walk(entry.get("contains", []) or [])

    walk(expansion.get("contains", []) or [])
    total = expansion.get("total")
    return SearchResult(
        operation=OP_EXPAND,
        concepts=tuple(concepts),
        total=total if isinstance(total, int) else None,
    )


def _parse_lookup(data: Mapping[str, Any], system: str, code: str) -> Concept | None:
    values = _parameter_values(data)
    display = _as_str(values.get("display"))
    if not display:
        return None
    designations: list[Designation] = []
    inactive = False
    for parameter in data.get("parameter", []) or []:
        parts = {p.get("name"): p for p in parameter.get("part", []) or []}
        if parameter.get("name") == "designation" and "value" in parts:
            value = _as_str(parts["value"].get("valueString"))
            status = _as_str((parts.get("status") or {}).get("valueCode"))
            if value and status != "inactive":
                designations.append(
                    Designation(
                        value=value,
                        language=_as_str((parts.get("language") or {}).get("valueCode")),
                        use=_as_str(
                            ((parts.get("use") or {}).get("valueCoding") or {}).get("code")
                        ),
                    )
                )
        if (
            parameter.get("name") == "property"
            and "code" in parts
            and parts["code"].get("valueCode") == "inactive"
        ):
            inactive = bool((parts.get("value") or {}).get("valueBoolean", False))
    return Concept(
        system=_as_str(values.get("system")) or system,
        code=_as_str(values.get("code")) or code,
        display=display,
        version=_as_str(values.get("version")),
        designations=tuple(designations),
        inactive=inactive,
    )
