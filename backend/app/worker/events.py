"""Job status events: a wake-up signal over Redis pub/sub.

The database (``job_events``) is the source of truth; a published message only tells SSE
streams to re-read it. That keeps ordering and de-duplication trivial and makes a missed
message harmless (streams also re-read on a timeout). Payloads are PHI-free event JSON.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from uuid import UUID

import redis
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

__all__ = ["EventBus", "MemoryEventBus", "RedisEventBus", "Subscription", "channel_name"]


def channel_name(job_id: UUID) -> str:
    return f"ips:job:{job_id}:events"


class Subscription(Protocol):
    async def next(self, timeout: float) -> str | None:
        """The next message, or ``None`` after ``timeout`` seconds."""
        ...


class EventBus(Protocol):
    def publish(self, job_id: UUID, payload: str) -> None: ...

    def subscribe(self, job_id: UUID) -> AbstractAsyncContextManager[Subscription]: ...


class _RedisSubscription:
    def __init__(self, pubsub: aioredis.client.PubSub) -> None:
        self._pubsub = pubsub

    async def next(self, timeout: float) -> str | None:
        message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if message is None:
            return None
        data = message.get("data")
        return data.decode() if isinstance(data, bytes) else str(data)


class RedisEventBus:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client = redis.Redis.from_url(url)

    def publish(self, job_id: UUID, payload: str) -> None:
        try:
            self._client.publish(channel_name(job_id), payload)
        except redis.RedisError as exc:
            # Non-fatal: the event is stored; streams re-read the database on a timeout.
            logger.warning("publishing a job event failed: %s", type(exc).__name__)

    @asynccontextmanager
    async def subscribe(self, job_id: UUID) -> AsyncIterator[Subscription]:
        client = aioredis.Redis.from_url(self._url)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel_name(job_id))
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.aclose()  # type: ignore[no-untyped-call]
            await client.aclose()


class _MemorySubscription:
    def __init__(self, bus: MemoryEventBus, job_id: UUID) -> None:
        self._bus = bus
        self._job_id = job_id
        self._cursor = bus.count(job_id)

    async def next(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while True:
            message = self._bus.get(self._job_id, self._cursor)
            if message is not None:
                self._cursor += 1
                return message
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.02)


class MemoryEventBus:
    """In-process bus for tests and single-process dev runs (thread-safe)."""

    def __init__(self) -> None:
        self._messages: dict[UUID, list[str]] = {}
        self._lock = threading.Lock()

    def publish(self, job_id: UUID, payload: str) -> None:
        with self._lock:
            self._messages.setdefault(job_id, []).append(payload)

    def count(self, job_id: UUID) -> int:
        with self._lock:
            return len(self._messages.get(job_id, []))

    def get(self, job_id: UUID, index: int) -> str | None:
        with self._lock:
            messages = self._messages.get(job_id, [])
            return messages[index] if index < len(messages) else None

    @asynccontextmanager
    async def subscribe(self, job_id: UUID) -> AsyncIterator[Subscription]:
        yield _MemorySubscription(self, job_id)
