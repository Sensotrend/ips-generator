"""The pipeline job (run by RQ, or inline in tests).

Idempotent: a job that already has a result (``review`` / ``approved`` / ``failed``) is skipped,
and a re-run of an interrupted job replaces its source and draft. Never logs document content
or exception messages (they can contain PHI, e.g. a Pydantic error's input value); only the job
id, step and exception class.
"""

from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache
from uuid import UUID

from rq.timeouts import JobTimeoutException
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import Draft, Job, JobSource
from app.pipeline.run import PipelineError, StepEvent, StepName, run_pipeline
from app.review.draft import new_draft
from app.schemas.api import JobStatus
from app.services import Services, build_services
from app.storage.objects import ObjectStoreError

logger = logging.getLogger(__name__)

__all__ = ["process_job", "run_job"]

_DONE = frozenset({JobStatus.REVIEW, JobStatus.APPROVED, JobStatus.FAILED})


@lru_cache
def _worker_services() -> Services:
    return build_services(get_settings())


# A forked RQ work-horse must not reuse the parent's pooled DB/Redis connections.
os.register_at_fork(after_in_child=_worker_services.cache_clear)


def run_job(job_id: str) -> None:
    """RQ entry point."""
    process_job(UUID(job_id), _worker_services())


def _fail(services: Services, job_id: UUID, step: str | None, code: str, message: str) -> None:
    with services.session() as session, session.begin():
        job = session.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_step = step
            job.error_code = code
            job.error_message = message
        services.audit(
            session, actor="worker", action="job.failed", job_id=job_id, step=step, code=code
        )
    services.record_event(job_id, "job", "failed", {"code": code, "step": step or ""})
    logger.info("job %s failed at %s: %s", job_id, step, code)


def process_job(job_id: UUID, services: Services) -> None:
    with services.session() as session, session.begin():
        job = session.get(Job, job_id)
        if job is None:
            logger.warning("job %s not found", job_id)
            return
        if JobStatus(job.status) in _DONE:
            logger.info("job %s already processed (%s); skipping", job_id, job.status)
            return
        job.status = JobStatus.RUNNING
        job.attempts += 1
        object_key, media_type, sha256 = job.object_key, job.media_type, job.sha256
    services.record_event(job_id, "job", "running")

    def on_event(event: StepEvent) -> None:
        services.record_event(job_id, event.step.value, event.status.value, dict(event.detail))

    try:
        data = services.store.get(object_key)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise PipelineError(
                StepName.INGEST, "integrity_error", "The stored original does not match its hash."
            )
        output = run_pipeline(
            data,
            media_type,
            extractor=services.extractor(),
            on_event=on_event,
            hooks=services.hooks,
            validator=services.validator,
            now=services.now(),
        )
    except PipelineError as exc:
        _fail(services, job_id, exc.step.value, exc.code, exc.message)
        return
    except JobTimeoutException:
        _fail(services, job_id, None, "job_timeout", "Processing took too long and was stopped.")
        raise
    except ObjectStoreError:
        _fail(services, job_id, None, "storage_error", "The original document could not be read.")
        return
    except Exception as exc:
        logger.error("job %s failed with %s", job_id, type(exc).__name__)
        _fail(services, job_id, None, "internal_error", "Processing failed unexpectedly.")
        return

    state = new_draft(
        output.enriched,
        flags=output.flags,
        dropped=output.dropped,
        validation=output.validation,
        validation_error=output.validation_error,
    )
    with services.session() as session, session.begin():
        session.execute(delete(JobSource).where(JobSource.job_id == job_id))
        session.execute(delete(Draft).where(Draft.job_id == job_id))
        session.add(JobSource(job_id=job_id, document=output.document.model_dump(mode="json")))
        session.add(
            Draft(
                job_id=job_id,
                version=1,
                state=state.model_dump(mode="json"),
                pipeline_meta={
                    "extractor_model": output.extractor_model,
                    "prompt_version": output.prompt_version,
                    "grounding": output.grounding_counts,
                    "derived": list(output.derived_paths),
                },
            )
        )
        job = session.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.REVIEW
            job.current_step = None
        services.audit(
            session,
            actor="worker",
            action="job.draft_ready",
            job_id=job_id,
            flags=len(output.flags),
            dropped=len(output.dropped),
            validation_passed=output.validation.passed if output.validation else None,
        )
    services.record_event(job_id, "job", "review_ready")
    logger.info("job %s ready for review", job_id)
