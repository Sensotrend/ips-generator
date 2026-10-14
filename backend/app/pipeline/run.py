"""Pipeline orchestrator for the API/worker (PLAN Phase 3).

ingest -> extract -> ground -> apply_grounding -> ``EnrichedIps.from_extraction`` ->
[derive (D-10), hook] -> [terminology coding, hook] -> assemble -> [validate (Matchbox), optional]

Same shape as the eval pipeline in ``evals/runner.py`` (which stays separate). Every step emits a
`StepEvent` (started / completed / skipped / failed) through ``on_event``; event details are
counts and fixed strings only, never document content (CLAUDE.md).

Hooks
-----
Two steps are being built elsewhere and are plugged in through `PipelineHooks`:

* ``derive`` (D-10): derive birth date / sex from a valid Finnish personal identity code when the
  document does not state them (``app.pipeline.derive``, results in
  ``EnrichedIps.patient_derived``). Returns the updated ``EnrichedIps`` plus its review flags
  (``derived_from_identity_code``, conflicts); derived values must be confirmed by the reviewer.
* ``terminology``: fill ``Enriched.codings`` from terminology-server lookups (D2).

`default_hooks` always runs ``derive``; ``terminology`` runs when ``TERMINOLOGY_MODE`` is not
``off``. A failing terminology step is reported as ``failed`` and the job continues without codes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.fhir.models import Bundle
from app.llm.client import create_client
from app.pipeline.assemble import AssemblyNote, AssemblyResult, assemble
from app.pipeline.derive import apply_derivations
from app.pipeline.extractors import Extractor, ReplayMissError
from app.pipeline.ground import ReviewFlag, apply_grounding, ground
from app.pipeline.ingest import IngestError, ingest
from app.pipeline.terminology import code_enriched
from app.pipeline.validate import MatchboxError, ValidationResult, blocking_unmatched_entries
from app.schemas.intermediate import EnrichedIps
from app.schemas.source import IngestedDocument
from app.terminology.client import TerminologyClient

__all__ = [
    "DeriveHook",
    "DeriveOutcome",
    "PipelineError",
    "PipelineHooks",
    "PipelineOutput",
    "StepEvent",
    "StepName",
    "StepStatus",
    "TerminologyHook",
    "ValidationSummary",
    "Validator",
    "default_hooks",
    "detect_derived_paths",
    "run_pipeline",
    "summarise_validation",
]


class StepName(StrEnum):
    INGEST = "ingest"
    EXTRACT = "extract"
    GROUND = "ground"
    DERIVE = "derive"
    TERMINOLOGY = "terminology"
    ASSEMBLE = "assemble"
    VALIDATE = "validate"


class StepStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class StepEvent(BaseModel):
    """Progress of one pipeline step. ``detail`` holds counts / fixed strings only (no PHI)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: StepName
    status: StepStatus
    detail: dict[str, int | str | bool] = Field(default_factory=dict)


# ---- hooks ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeriveOutcome:
    enriched: EnrichedIps
    flags: tuple[ReviewFlag, ...] = ()
    """Review flags of the derivation (paths ``patient.birth_date`` / ``patient.gender`` /
    ``patient.identifiers``)."""


type DeriveHook = Callable[[EnrichedIps], DeriveOutcome]
type TerminologyHook = Callable[[EnrichedIps], EnrichedIps]
type Validator = Callable[[Bundle], ValidationResult]


@dataclass(frozen=True)
class PipelineHooks:
    derive: DeriveHook | None = None
    terminology: TerminologyHook | None = None


def default_hooks(settings: Settings | None = None) -> PipelineHooks:
    """The hooks the worker uses: D-10 derivation always; terminology per ``terminology_mode``."""
    settings = settings or get_settings()

    def derive(enriched: EnrichedIps) -> DeriveOutcome:
        updated, flags = apply_derivations(enriched)
        return DeriveOutcome(updated, flags)

    terminology: TerminologyHook | None = None
    if settings.terminology_mode != "off":
        terminology = _terminology_hook(settings)
    return PipelineHooks(derive=derive, terminology=terminology)


def _terminology_hook(settings: Settings) -> TerminologyHook:
    clients: dict[str, Any] = {}  # created on first use, then reused (keeps the lookup cache)

    def code(enriched: EnrichedIps) -> EnrichedIps:
        if "tx" not in clients:
            clients["tx"] = TerminologyClient(settings=settings)
            if settings.terminology_mode == "llm":
                clients["llm"] = create_client(settings)
        result = code_enriched(enriched, tx=clients["tx"], llm=clients.get("llm"))
        return result.enriched

    return code


DERIVED_FIELDS = ("birth_date", "gender")


def detect_derived_paths(enriched: EnrichedIps) -> tuple[str, ...]:
    """``patient.<field>`` for every patient fact that has a derived value (D-10).

    Read through ``getattr`` so this module does not depend on the exact shape of
    ``EnrichedIps.patient_derived``; anything present there must be confirmed in review.
    """
    derived = getattr(enriched, "patient_derived", None)
    return tuple(
        f"patient.{name}" for name in DERIVED_FIELDS if getattr(derived, name, None) is not None
    )


# ---- validation summary -----------------------------------------------------------------------


class IssueSummary(BaseModel):
    """A validator issue without its message (messages can quote resource content)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Literal["fatal", "error", "warning", "information"]
    message_id: str | None
    path: str


class ValidationSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: str
    errors: int
    warnings: int
    unmatched_entries: list[int]
    allowed_unmatched_entries: list[int] = []
    """Unmatched entries the gate accepts (non-IPS Observations, PLAN.md D-15)."""
    passed: bool
    """No errors and no blocking unmatched Bundle entries (see ``app.pipeline.validate``)."""
    issues: list[IssueSummary]


def summarise_validation(result: ValidationResult, bundle: Bundle) -> ValidationSummary:
    """``bundle`` is the Bundle that was validated (to tell allowed unmatched entries apart)."""
    unmatched = result.unmatched_bundle_entries
    blocking = blocking_unmatched_entries(result, bundle)
    return ValidationSummary(
        profile=result.profile,
        errors=len(result.errors),
        warnings=len(result.warnings),
        unmatched_entries=unmatched,
        allowed_unmatched_entries=[i for i in unmatched if i not in blocking],
        passed=not result.errors and not blocking,
        issues=[
            IssueSummary(severity=i.severity, message_id=i.message_id, path=i.path)
            for i in result.issues
            if i.severity != "information" or "does not match any known slice" in i.message
        ],
    )


# ---- run --------------------------------------------------------------------------------------


class PipelineError(Exception):
    """A step failed. ``code`` and ``message`` are PHI-free and safe to show and store."""

    def __init__(self, step: StepName, code: str, message: str) -> None:
        super().__init__(message)
        self.step = step
        self.code = code
        self.message = message


class PipelineOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    document: IngestedDocument
    enriched: EnrichedIps
    flags: tuple[ReviewFlag, ...]
    dropped: tuple[str, ...]
    derived_paths: tuple[str, ...]
    grounding_counts: dict[str, int]
    extractor_model: str
    prompt_version: str | None
    notes: tuple[AssemblyNote, ...]
    validation: ValidationSummary | None
    validation_error: str | None = None


type EventSink = Callable[[StepEvent], None]


def _emit(sink: EventSink, step: StepName, status: StepStatus, **detail: Any) -> None:
    sink(StepEvent(step=step, status=status, detail=detail))


def run_pipeline(
    data: bytes,
    media_type: str,
    *,
    extractor: Extractor,
    on_event: EventSink,
    hooks: PipelineHooks | None = None,
    validator: Validator | None = None,
    filename: str | None = None,
    now: dt.datetime | None = None,
) -> PipelineOutput:
    """Run the pipeline on one uploaded document. Raises `PipelineError` on a fatal step."""
    hooks = hooks or PipelineHooks()
    now = now or dt.datetime.now(dt.UTC)

    _emit(on_event, StepName.INGEST, StepStatus.STARTED)
    try:
        doc = ingest(data, media_type, filename)
    except IngestError as exc:
        # Ingest error messages never contain document text (ingest.py contract).
        raise PipelineError(StepName.INGEST, type(exc).__name__, str(exc)) from exc
    _emit(
        on_event,
        StepName.INGEST,
        StepStatus.COMPLETED,
        pages=doc.page_count,
        segments=len(doc.segments),
        pages_without_text=len(doc.pages_without_text),
    )

    _emit(on_event, StepName.EXTRACT, StepStatus.STARTED, extractor=extractor.name)
    try:
        extracted = extractor(data, doc)
    except ReplayMissError as exc:
        raise PipelineError(StepName.EXTRACT, "replay_no_answer", str(exc)) from exc
    except Exception as exc:
        # Extraction errors are typed and PHI-free, but keep only the class name to be safe.
        raise PipelineError(
            StepName.EXTRACT, type(exc).__name__, "Extraction failed; see server logs."
        ) from exc
    _emit(on_event, StepName.EXTRACT, StepStatus.COMPLETED, model=extracted.model)

    _emit(on_event, StepName.GROUND, StepStatus.STARTED)
    report = ground(extracted.extraction, doc)
    grounded = apply_grounding(extracted.extraction, report)
    counts = {status.value: n for status, n in report.counts.items()}
    _emit(
        on_event,
        StepName.GROUND,
        StepStatus.COMPLETED,
        flags=len(grounded.flags),
        dropped=len(grounded.dropped),
        **counts,
    )

    enriched = EnrichedIps.from_extraction(grounded.extraction)

    flags = grounded.flags
    if hooks.derive is None:
        _emit(on_event, StepName.DERIVE, StepStatus.SKIPPED, reason="not_configured")
    else:
        _emit(on_event, StepName.DERIVE, StepStatus.STARTED)
        outcome = hooks.derive(enriched)
        enriched = outcome.enriched
        flags = (*flags, *outcome.flags)
        _emit(
            on_event,
            StepName.DERIVE,
            StepStatus.COMPLETED,
            derived=len(detect_derived_paths(enriched)),
            flags=len(outcome.flags),
        )
    derived_paths = detect_derived_paths(enriched)

    if hooks.terminology is None:
        _emit(on_event, StepName.TERMINOLOGY, StepStatus.SKIPPED, reason="not_configured")
    else:
        _emit(on_event, StepName.TERMINOLOGY, StepStatus.STARTED)
        try:
            enriched = hooks.terminology(enriched)
        except Exception as exc:  # coding is optional: text-only entries are valid IPS
            _emit(on_event, StepName.TERMINOLOGY, StepStatus.FAILED, reason=type(exc).__name__)
        else:
            _emit(on_event, StepName.TERMINOLOGY, StepStatus.COMPLETED)

    _emit(on_event, StepName.ASSEMBLE, StepStatus.STARTED)
    try:
        assembly: AssemblyResult = assemble(enriched, now=now, flags=flags)
    except Exception as exc:
        raise PipelineError(
            StepName.ASSEMBLE, type(exc).__name__, "FHIR assembly failed; see server logs."
        ) from exc
    _emit(
        on_event,
        StepName.ASSEMBLE,
        StepStatus.COMPLETED,
        entries=len(assembly.bundle.entry or []),
        warnings=len(assembly.warnings),
    )

    validation: ValidationSummary | None = None
    validation_error: str | None = None
    if validator is None:
        _emit(on_event, StepName.VALIDATE, StepStatus.SKIPPED, reason="not_configured")
    else:
        _emit(on_event, StepName.VALIDATE, StepStatus.STARTED)
        try:
            validation = summarise_validation(validator(assembly.bundle), assembly.bundle)
        except MatchboxError:
            validation_error = "validator_unavailable"
            _emit(on_event, StepName.VALIDATE, StepStatus.FAILED, reason=validation_error)
        else:
            _emit(
                on_event,
                StepName.VALIDATE,
                StepStatus.COMPLETED,
                passed=validation.passed,
                errors=validation.errors,
                warnings=validation.warnings,
                unmatched=len(validation.unmatched_entries),
            )

    return PipelineOutput(
        document=doc,
        enriched=enriched,
        flags=flags,
        dropped=grounded.dropped,
        derived_paths=derived_paths,
        grounding_counts=counts,
        extractor_model=extracted.model,
        prompt_version=extracted.prompt_version,
        notes=assembly.notes,
        validation=validation,
        validation_error=validation_error,
    )
