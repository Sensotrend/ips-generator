"""Step 7: validate Bundles against the IPS IG with Matchbox (``$validate``).

Synchronous by design: the pipeline runs inside RQ worker jobs (synchronous functions) and this is
a single blocking HTTP call per Bundle. Async callers can wrap it in ``anyio.to_thread.run_sync``.

Matchbox answers ``$validate`` with HTTP 200 and an ``OperationOutcome`` for valid *and* invalid
input (including unparsable JSON, reported as a ``fatal`` issue). A problem with the validator
itself (e.g. unknown profile, IG not installed) is also a 200 OperationOutcome, with an
``exception`` issue from the ``ValidationProvider``; that case raises :class:`MatchboxError` instead
of being reported as an invalid Bundle.

Caveat (seen with Matchbox 4.1.21 / IPS 2.0.1): Bundle entries are sliced by "resource conforms to
profile X". An entry that fails its IPS profile does not match the slice, so its profile errors are
**not** reported; the only trace is an ``information`` issue "This element does not match any known
slice" on ``Bundle.entry[n]``. :attr:`ValidationResult.unmatched_bundle_entries` exposes these so
the pipeline can treat them as failures (entries that legitimately have no slice, such as
``Provenance``, also appear there).

PHI: issue messages can quote resource content. Never log them; this module logs counts only.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.fhir.constants import PROFILE_BUNDLE_VERSIONED
from app.fhir.models import Bundle

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 300.0
"""Generous: the first validation after a Matchbox start loads the IG and can take minutes."""

_ISSUE_SOURCE_URL = "http://hl7.org/fhir/StructureDefinition/operationoutcome-issue-source"
_MESSAGE_ID_URL = "http://hl7.org/fhir/StructureDefinition/operationoutcome-message-id"
_BUNDLE_ENTRY_RE = re.compile(r"^Bundle\.entry\[(\d+)\]$")
_NO_SLICE_TEXT = "does not match any known slice"

Severity = Literal["fatal", "error", "warning", "information"]


class MatchboxError(RuntimeError):
    """Matchbox could not perform the validation (unreachable, bad response, setup problem)."""


class ValidationIssue(BaseModel):
    """One ``OperationOutcome.issue``, flattened."""

    model_config = ConfigDict(frozen=True)

    severity: Severity
    code: str
    message: str = ""
    """``diagnostics`` (or ``details.text``). May quote resource content: never log it."""
    expression: tuple[str, ...] = ()
    location: tuple[str, ...] = ()
    message_id: str | None = None
    """Validator message id (e.g. ``Bundle_BUNDLE_Entry_NoFirst``); stable across wordings."""
    source: str | None = None
    """Validator component that raised the issue (e.g. ``InstanceValidator``)."""

    @property
    def path(self) -> str:
        """First expression (FHIRPath), falling back to the first location, or ``""``."""
        return (self.expression or self.location or ("",))[0]

    @property
    def is_error(self) -> bool:
        return self.severity in ("error", "fatal")


class ValidationResult(BaseModel):
    """Parsed ``$validate`` OperationOutcome."""

    model_config = ConfigDict(frozen=True)

    profile: str
    issues: tuple[ValidationIssue, ...] = Field(default_factory=tuple)

    @property
    def errors(self) -> list[ValidationIssue]:
        """Issues with severity ``error`` or ``fatal``."""
        return [i for i in self.issues if i.is_error]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        """True when Matchbox reported no ``error``/``fatal`` issues (definition of done)."""
        return not self.errors

    @property
    def unmatched_bundle_entries(self) -> list[int]:
        """Indexes of Bundle entries that matched no Bundle slice (see module docstring)."""
        indexes: list[int] = []
        for issue in self.issues:
            match = _BUNDLE_ENTRY_RE.match(issue.path)
            if match and _NO_SLICE_TEXT in issue.message:
                indexes.append(int(match.group(1)))
        return indexes

    def counts(self) -> dict[str, int]:
        """Issue counts per severity (safe to log)."""
        result = dict.fromkeys(("fatal", "error", "warning", "information"), 0)
        for issue in self.issues:
            result[issue.severity] += 1
        return result


def _extension_value(issue: Mapping[str, Any], url: str) -> str | None:
    for ext in issue.get("extension") or ():
        if isinstance(ext, Mapping) and ext.get("url") == url:
            for key in ("valueString", "valueCode", "valueUri"):
                value = ext.get(key)
                if isinstance(value, str):
                    return value
    return None


def parse_operation_outcome(outcome: Mapping[str, Any], *, profile: str) -> ValidationResult:
    """Turn a Matchbox ``OperationOutcome`` into a :class:`ValidationResult`.

    Raises :class:`MatchboxError` if ``outcome`` is not an OperationOutcome or reports a validator
    setup problem rather than a validation result.
    """
    if outcome.get("resourceType") != "OperationOutcome":
        raise MatchboxError("Matchbox response is not an OperationOutcome")
    issues: list[ValidationIssue] = []
    for raw in outcome.get("issue") or ():
        details = raw.get("details") or {}
        issue = ValidationIssue(
            severity=raw.get("severity", "error"),
            code=raw.get("code", "unknown"),
            message=raw.get("diagnostics") or details.get("text") or "",
            expression=tuple(raw.get("expression") or ()),
            location=tuple(raw.get("location") or ()),
            message_id=_extension_value(raw, _MESSAGE_ID_URL),
            source=_extension_value(raw, _ISSUE_SOURCE_URL),
        )
        if issue.code == "exception" and issue.source == "ValidationProvider":
            # e.g. "Matchbox engine for profile '...' could not be created". The profile is
            # configuration, not patient data, so it is safe to include.
            raise MatchboxError(f"Matchbox could not validate against {profile}: {issue.message}")
        issues.append(issue)
    return ValidationResult(profile=profile, issues=tuple(issues))


class MatchboxClient:
    """Small synchronous client for Matchbox ``$validate``.

    Use as a context manager, or call :meth:`close`. Pass ``http_client`` to inject a configured
    :class:`httpx.Client` (tests use ``httpx.MockTransport``); it is then not closed by this class.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.base_url = (base_url or get_settings().matchbox_url).rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def validate(
        self,
        bundle: Bundle | Mapping[str, Any],
        *,
        profile: str = PROFILE_BUNDLE_VERSIONED,
    ) -> ValidationResult:
        """Validate ``bundle`` against ``profile`` (default: IPS Bundle 2.0.1)."""
        body = (
            bundle.to_fhir_json()
            if isinstance(bundle, Bundle)
            else json.dumps(bundle, ensure_ascii=False)
        )
        try:
            response = self._http.post(
                f"{self.base_url}/$validate",
                params={"profile": profile},
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/fhir+json",
                    "Accept": "application/fhir+json",
                },
            )
        except httpx.HTTPError as exc:
            raise MatchboxError(f"Matchbox request failed: {type(exc).__name__}") from exc
        try:
            outcome = response.json()
        except ValueError as exc:
            raise MatchboxError(
                f"Matchbox returned HTTP {response.status_code} without a JSON body"
            ) from exc
        if not isinstance(outcome, Mapping):
            raise MatchboxError(f"Matchbox returned HTTP {response.status_code}, unexpected body")
        # Non-2xx with an OperationOutcome is still a validation result (HAPI convention).
        result = parse_operation_outcome(outcome, profile=profile)
        logger.info("Matchbox validation: %s", result.counts())
        return result


def validate_bundle(
    bundle: Bundle | Mapping[str, Any],
    *,
    profile: str = PROFILE_BUNDLE_VERSIONED,
    base_url: str | None = None,
) -> ValidationResult:
    """Convenience wrapper: validate one Bundle with a short-lived :class:`MatchboxClient`."""
    with MatchboxClient(base_url) as client:
        return client.validate(bundle, profile=profile)
