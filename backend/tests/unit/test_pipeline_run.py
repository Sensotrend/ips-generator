"""Pipeline orchestrator (`app.pipeline.run`) and the replay extractor."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.pipeline.extractors import ExtractorConfigError, ReplayExtractor, ReplayMissError
from app.pipeline.run import (
    DeriveOutcome,
    PipelineError,
    PipelineHooks,
    StepEvent,
    StepName,
    StepStatus,
    default_hooks,
    detect_derived_paths,
    run_pipeline,
)
from app.pipeline.validate import ValidationResult
from app.schemas.intermediate import EnrichedIps
from tests.api_support import DATASET, dataset_document


@pytest.fixture(scope="module")
def replay() -> ReplayExtractor:
    return ReplayExtractor(DATASET)


def test_replay_knows_every_dataset_document(replay: ReplayExtractor) -> None:
    documents = list(DATASET.glob("*/document.*"))
    assert len(replay) == len(documents) >= 20
    assert all(replay.knows(p.read_bytes()) for p in documents)
    assert not replay.knows(b"anything else")


def test_replay_miss_message_is_fixed(replay: ReplayExtractor) -> None:
    with pytest.raises(ReplayMissError, match="use one of the eval documents"):
        replay(b"Potilas: X", None)  # type: ignore[arg-type]


def test_replay_needs_a_dataset(tmp_path: object) -> None:
    with pytest.raises(ExtractorConfigError):
        ReplayExtractor(DATASET / "does-not-exist")


def test_events_per_step_and_output(replay: ReplayExtractor) -> None:
    events: list[StepEvent] = []
    data = dataset_document("fi01_discharge_internal_txt").read_bytes()
    output = run_pipeline(
        data,
        "text/plain",
        extractor=replay,
        on_event=events.append,
        validator=lambda bundle: ValidationResult(profile="p"),
    )
    pairs = [(e.step, e.status) for e in events]
    assert pairs == [
        (StepName.INGEST, StepStatus.STARTED),
        (StepName.INGEST, StepStatus.COMPLETED),
        (StepName.EXTRACT, StepStatus.STARTED),
        (StepName.EXTRACT, StepStatus.COMPLETED),
        (StepName.GROUND, StepStatus.STARTED),
        (StepName.GROUND, StepStatus.COMPLETED),
        (StepName.DERIVE, StepStatus.SKIPPED),
        (StepName.TERMINOLOGY, StepStatus.SKIPPED),
        (StepName.ASSEMBLE, StepStatus.STARTED),
        (StepName.ASSEMBLE, StepStatus.COMPLETED),
        (StepName.VALIDATE, StepStatus.STARTED),
        (StepName.VALIDATE, StepStatus.COMPLETED),
    ]
    assert output.extractor_model == "replay"
    assert output.validation is not None
    assert output.validation.passed
    assert output.grounding_counts["exact"] > 0
    # Event details are counts / fixed strings only.
    text = data.decode()
    for event in events:
        for value in event.detail.values():
            assert not (isinstance(value, str) and len(value) > 3 and value in text)


def test_hooks_run_in_order(replay: ReplayExtractor) -> None:
    calls: list[str] = []

    def derive(enriched: EnrichedIps) -> DeriveOutcome:
        calls.append("derive")
        return DeriveOutcome(enriched)

    def terminology(enriched: EnrichedIps) -> EnrichedIps:
        calls.append("terminology")
        return enriched

    events: list[StepEvent] = []
    run_pipeline(
        dataset_document("fi01_discharge_internal_txt").read_bytes(),
        "text/plain",
        extractor=replay,
        on_event=events.append,
        hooks=PipelineHooks(derive=derive, terminology=terminology),
    )
    assert calls == ["derive", "terminology"]
    assert (StepName.DERIVE, StepStatus.COMPLETED) in [(e.step, e.status) for e in events]


def test_default_hooks_derive_always_terminology_per_setting() -> None:
    off = default_hooks(Settings(terminology_mode="off"))
    assert off.derive is not None
    assert off.terminology is None
    # Constructing the hook makes no requests; the client is created on first use.
    assert default_hooks(Settings(terminology_mode="deterministic")).terminology is not None


def test_default_derive_fills_birth_date_from_identity_code(replay: ReplayExtractor) -> None:
    hooks = default_hooks(Settings(terminology_mode="off"))
    case = next(
        p.parent.name
        for p in sorted(DATASET.glob("*/meta.json"))
        if "hetu_without_birth_date" in p.read_text(encoding="utf-8")
    )
    path = dataset_document(case)
    media_type = {
        "txt": "text/plain",
        "md": "text/plain",
        "json": "application/json",
        "csv": "text/csv",
        "pdf": "application/pdf",
    }[path.suffix.lstrip(".")]
    output = run_pipeline(
        path.read_bytes(), media_type, extractor=replay, on_event=lambda e: None, hooks=hooks
    )
    assert "patient.birth_date" in output.derived_paths
    assert output.derived_paths == detect_derived_paths(output.enriched)


def test_failing_terminology_step_does_not_fail_the_job(replay: ReplayExtractor) -> None:
    def terminology(enriched: EnrichedIps) -> EnrichedIps:
        raise ConnectionError("terminology server down")

    events: list[StepEvent] = []
    output = run_pipeline(
        dataset_document("fi01_discharge_internal_txt").read_bytes(),
        "text/plain",
        extractor=replay,
        on_event=events.append,
        hooks=PipelineHooks(terminology=terminology),
    )
    failed = [e for e in events if e.step is StepName.TERMINOLOGY and e.status is StepStatus.FAILED]
    assert failed
    assert failed[0].detail == {"reason": "ConnectionError"}
    assert output.enriched is not None
    assert (StepName.ASSEMBLE, StepStatus.COMPLETED) in [(e.step, e.status) for e in events]


def test_ingest_failure_is_a_pipeline_error(replay: ReplayExtractor) -> None:
    with pytest.raises(PipelineError) as info:
        run_pipeline(b"%PDF-1.4 broken", "application/pdf", extractor=replay, on_event=print)
    assert info.value.step is StepName.INGEST
    assert info.value.code == "CorruptDocumentError"


def test_extractor_exception_message_is_not_propagated(replay: ReplayExtractor) -> None:
    def boom(data: bytes, doc: object) -> object:
        raise ValueError("Potilas Aino Testinen")

    boom.name = "boom"  # type: ignore[attr-defined]
    with pytest.raises(PipelineError) as info:
        run_pipeline(b"hello world", "text/plain", extractor=boom, on_event=lambda e: None)  # type: ignore[arg-type]
    assert info.value.code == "ValueError"
    assert "Aino" not in info.value.message
