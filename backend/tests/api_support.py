"""In-process services for API/worker tests: SQLite, in-memory storage and events, the replay
extractor over the eval dataset, jobs run inline. No network, no paid calls."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.config import ExtractorKind, Settings
from app.db.models import Base
from app.db.session import make_engine, make_session_factory
from app.pipeline.extractors import ReplayExtractor
from app.pipeline.run import PipelineHooks, Validator
from app.services import Services
from app.storage.objects import MemoryObjectStore
from app.worker.events import MemoryEventBus
from app.worker.queue import InlineJobQueue
from app.worker.tasks import process_job

DATASET = Path(__file__).resolve().parents[2] / "evals" / "dataset"


def dataset_document(case_id: str) -> Path:
    return next((DATASET / case_id).glob("document.*"))


def make_services(
    *,
    hooks: PipelineHooks | None = None,
    validator: Validator | None = None,
    inline: bool = True,
    settings: Settings | None = None,
) -> Services:
    settings = settings or Settings(
        app_env="development",
        extractor=ExtractorKind.REPLAY,
        replay_dataset_dir=DATASET,
        validate_with_matchbox=validator is not None,
    )
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    services = Services(
        settings=settings,
        session_factory=make_session_factory(engine),
        store=MemoryObjectStore(),
        bus=MemoryEventBus(),
        extractor_factory=lambda: ReplayExtractor(DATASET),
        hooks=hooks or PipelineHooks(),
        validator=validator,
    )
    if inline:
        runner: Callable[..., None] = lambda job_id: process_job(job_id, services)  # noqa: E731
        services.queue = InlineJobQueue(runner)
    return services
