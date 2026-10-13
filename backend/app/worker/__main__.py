"""Run the pipeline worker: ``uv run python -m app.worker [--simple]``.

``--simple`` runs jobs in the worker process (no fork per job; use on macOS, where forking a
process that has loaded system frameworks can crash). The job timeout applies in both modes.
"""

from __future__ import annotations

import argparse
import logging

from redis import Redis
from rq import Queue, SimpleWorker, Worker

from app.config import get_settings
from app.services import check_runtime_config
from app.worker.tasks import _worker_services


def main() -> None:
    parser = argparse.ArgumentParser(description="IPS pipeline worker (RQ)")
    parser.add_argument("--simple", action="store_true", help="no fork per job (macOS)")
    parser.add_argument("--burst", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    check_runtime_config(settings)
    _worker_services().extractor()  # fail fast on extractor misconfiguration

    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.job_queue_name, connection=connection)
    worker_class = SimpleWorker if args.simple else Worker
    worker = worker_class([queue], connection=connection)
    worker.work(burst=args.burst, with_scheduler=False)


if __name__ == "__main__":
    main()
