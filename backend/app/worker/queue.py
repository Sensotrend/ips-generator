"""Job queue: RQ in normal operation, inline execution for tests / single-process dev."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from redis import Redis
from rq import Queue

__all__ = ["TASK", "InlineJobQueue", "JobQueue", "RqJobQueue", "rq_job_id"]

TASK = "app.worker.tasks.run_job"


def rq_job_id(job_id: UUID) -> str:
    return f"pipeline-{job_id}"


class JobQueue(Protocol):
    def enqueue(self, job_id: UUID) -> None: ...


class RqJobQueue:
    def __init__(self, redis_url: str, *, name: str, timeout_s: int) -> None:
        self._queue = Queue(name, connection=Redis.from_url(redis_url))
        self._timeout_s = timeout_s

    def enqueue(self, job_id: UUID) -> None:
        # The RQ job id is derived from our job id, and the task itself skips jobs that are
        # already processed, so enqueueing twice is harmless (idempotent).
        self._queue.enqueue(
            TASK,
            str(job_id),
            job_id=rq_job_id(job_id),
            job_timeout=self._timeout_s,
            result_ttl=3600,
            failure_ttl=7 * 24 * 3600,
            description="ips pipeline job",
        )


class InlineJobQueue:
    """Runs the job immediately in the calling thread."""

    def __init__(self, runner: Callable[[UUID], None]) -> None:
        self._runner = runner

    def enqueue(self, job_id: UUID) -> None:
        self._runner(job_id)
