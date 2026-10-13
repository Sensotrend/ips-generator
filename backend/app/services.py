"""Service container shared by the API and the worker (database, storage, events, queue)."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import AuthMode, ExtractorKind, Settings
from app.db.models import AuditEvent, Job, JobEvent, utcnow
from app.db.session import make_engine, make_session_factory
from app.fhir.models import Bundle
from app.pipeline.extractors import Extractor, ExtractorConfigError, build_extractor
from app.pipeline.run import PipelineHooks, Validator, default_hooks
from app.pipeline.validate import ValidationResult, validate_bundle
from app.schemas.api import JobEventOut
from app.storage.objects import ObjectStore, S3ObjectStore
from app.worker.events import EventBus, RedisEventBus
from app.worker.queue import InlineJobQueue, JobQueue, RqJobQueue

logger = logging.getLogger(__name__)

__all__ = ["ConfigError", "Services", "build_services", "check_runtime_config"]


class ConfigError(RuntimeError):
    """The process must not start with this configuration."""


def check_runtime_config(settings: Settings) -> None:
    """Refuse unsafe configurations (called at API and worker start-up)."""
    if settings.auth_mode is AuthMode.OIDC:
        raise ConfigError("AUTH_MODE=oidc is not implemented yet (PLAN Phase 3, deferred).")
    if not settings.is_development:
        raise ConfigError(
            "Refusing to start: no authentication is configured. The fixed dev reviewer "
            "identity is only allowed with APP_ENV=development (OIDC is not implemented yet)."
        )
    if settings.extractor is ExtractorKind.REPLAY and not settings.is_development:
        raise ConfigError("EXTRACTOR=replay is only allowed with APP_ENV=development.")


@dataclass
class Services:
    settings: Settings
    session_factory: sessionmaker[Session]
    store: ObjectStore
    bus: EventBus
    extractor_factory: Callable[[], Extractor]
    hooks: PipelineHooks = field(default_factory=PipelineHooks)
    validator: Validator | None = None
    queue: JobQueue | None = None
    wallet_transport: httpx.BaseTransport | None = None
    """Test seam for the wallet issuer HTTP client; ``None`` = real network."""
    _extractor: Extractor | None = None

    def session(self) -> Session:
        return self.session_factory()

    def extractor(self) -> Extractor:
        if self._extractor is None:
            self._extractor = self.extractor_factory()
        return self._extractor

    def enqueue(self, job_id: UUID) -> None:
        if self.queue is None:
            raise ConfigError("no job queue configured")
        self.queue.enqueue(job_id)

    # ---- events / audit -----------------------------------------------------------------

    def record_event(
        self,
        job_id: UUID,
        step: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> JobEventOut:
        """Store a job event (PHI-free ``detail``) and wake up its SSE streams."""
        for attempt in range(3):
            try:
                with self.session() as session, session.begin():
                    seq = (
                        session.scalar(
                            select(func.max(JobEvent.seq)).where(JobEvent.job_id == job_id)
                        )
                        or 0
                    ) + 1
                    row = JobEvent(
                        job_id=job_id,
                        seq=seq,
                        step=step,
                        status=status,
                        detail=detail or {},
                        created_at=utcnow(),
                    )
                    session.add(row)
                    if step != "job":
                        job = session.get(Job, job_id)
                        if job is not None:
                            job.current_step = step
                break
            except IntegrityError:
                if attempt == 2:
                    raise
        event = JobEventOut(
            seq=row.seq, step=row.step, status=row.status, detail=row.detail, at=row.created_at
        )
        self.bus.publish(job_id, event.model_dump_json())
        return event

    @staticmethod
    def audit(
        session: Session, *, actor: str, action: str, job_id: UUID | None, **details: Any
    ) -> None:
        """Append an audit event in the caller's transaction (paths/counts only, no PHI)."""
        session.add(
            AuditEvent(at=utcnow(), actor=actor, action=action, job_id=job_id, details=details)
        )

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC)


def _matchbox_validator(settings: Settings) -> Validator:
    def validate(bundle: Bundle) -> ValidationResult:
        return validate_bundle(bundle, base_url=settings.matchbox_url)

    return validate


def build_services(settings: Settings) -> Services:
    """Real services from settings (Postgres, MinIO/S3, Redis, RQ, Matchbox)."""
    check_runtime_config(settings)
    if settings.s3_access_key is None or settings.s3_secret_key is None:
        raise ConfigError("S3_ACCESS_KEY and S3_SECRET_KEY must be set")

    def extractor_factory() -> Extractor:
        try:
            return build_extractor(settings)
        except ExtractorConfigError as exc:
            raise ConfigError(str(exc)) from exc

    services = Services(
        settings=settings,
        session_factory=make_session_factory(make_engine(settings.database_url)),
        store=S3ObjectStore(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key.get_secret_value(),
            secret_key=settings.s3_secret_key.get_secret_value(),
            bucket=settings.s3_bucket,
        ),
        bus=RedisEventBus(settings.redis_url),
        extractor_factory=extractor_factory,
        hooks=default_hooks(),
        validator=_matchbox_validator(settings) if settings.validate_with_matchbox else None,
    )
    if settings.run_jobs_inline:
        from app.worker.tasks import process_job

        services.queue = InlineJobQueue(lambda job_id: process_job(job_id, services))
    else:
        services.queue = RqJobQueue(
            settings.redis_url, name=settings.job_queue_name, timeout_s=settings.job_timeout_s
        )
    return services
