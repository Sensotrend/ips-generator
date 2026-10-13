"""Worker task: idempotency and failure handling."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from rq.timeouts import JobTimeoutException
from sqlalchemy import func, select

from app.db.models import Draft, Job, JobEvent
from app.schemas.api import JobStatus
from app.services import Services
from app.worker.tasks import process_job
from tests.api_support import dataset_document, make_services


def _job(services: Services, data: bytes, media_type: str = "text/plain") -> uuid.UUID:
    job_id = uuid.uuid4()
    services.store.put(f"jobs/{job_id}/original", data, media_type)
    with services.session() as session, session.begin():
        session.add(
            Job(
                id=job_id,
                status=JobStatus.QUEUED,
                created_by="dev-reviewer",
                media_type=media_type,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                object_key=f"jobs/{job_id}/original",
                extractor="replay",
            )
        )
    return job_id


def _status(services: Services, job_id: uuid.UUID) -> str:
    with services.session() as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job.status


def _event_count(services: Services, job_id: uuid.UUID) -> int:
    with services.session() as session:
        return session.scalar(select(func.count()).where(JobEvent.job_id == job_id)) or 0


def test_processing_twice_is_a_no_op() -> None:
    services = make_services(inline=False)
    job_id = _job(services, dataset_document("fi01_discharge_internal_txt").read_bytes())
    process_job(job_id, services)
    assert _status(services, job_id) == JobStatus.REVIEW
    events = _event_count(services, job_id)
    process_job(job_id, services)
    assert _event_count(services, job_id) == events
    with services.session() as session:
        assert session.scalar(select(func.count()).select_from(Draft)) == 1


def test_interrupted_job_is_rerun() -> None:
    services = make_services(inline=False)
    job_id = _job(services, dataset_document("fi01_discharge_internal_txt").read_bytes())
    with services.session() as session, session.begin():
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.RUNNING  # a worker died mid-job
    process_job(job_id, services)
    assert _status(services, job_id) == JobStatus.REVIEW


def test_tampered_original_fails() -> None:
    services = make_services(inline=False)
    job_id = _job(services, b"original text")
    services.store.put(f"jobs/{job_id}/original", b"changed", "text/plain")
    process_job(job_id, services)
    with services.session() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert (job.status, job.error_code) == (JobStatus.FAILED, "integrity_error")


def test_timeout_marks_job_failed() -> None:
    services = make_services(inline=False)

    def slow(data: bytes, doc: object) -> object:
        raise JobTimeoutException("timeout")

    slow.name = "slow"  # type: ignore[attr-defined]
    services._extractor = slow  # type: ignore[assignment]
    job_id = _job(services, dataset_document("fi01_discharge_internal_txt").read_bytes())
    # A timeout inside the extractor surfaces as an extraction PipelineError...
    process_job(job_id, services)
    with services.session() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED


def test_timeout_outside_steps_is_reraised_for_rq() -> None:
    services = make_services(inline=False)
    job_id = _job(services, b"x")

    class TimingOutStore:
        def put(self, key: str, data: bytes, content_type: str) -> None: ...

        def get(self, key: str) -> bytes:
            raise JobTimeoutException("timeout")

    services.store = TimingOutStore()
    with pytest.raises(JobTimeoutException):
        process_job(job_id, services)
    with services.session() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert (job.status, job.error_code) == (JobStatus.FAILED, "job_timeout")
