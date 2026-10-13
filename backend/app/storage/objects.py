"""Original documents in S3-compatible object storage.

Encryption at rest: **not enabled yet.** MinIO server-side encryption needs a KMS (MinIO KES or
an external KMS), which the dev compose stack does not run. Production must use a bucket with
SSE (e.g. S3 SSE-KMS) before any real data (PLAN §2 "object storage (originals, encrypted)").
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

__all__ = ["MemoryObjectStore", "ObjectStore", "ObjectStoreError", "S3ObjectStore"]


class ObjectStoreError(RuntimeError):
    """Storage failed (message has no document content)."""


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...


class S3ObjectStore:
    def __init__(self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        self._bucket = bucket
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStoreError(f"storing the original failed ({type(exc).__name__})") from exc

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStoreError(f"reading the original failed ({type(exc).__name__})") from exc


class MemoryObjectStore:
    """In-process store for tests and single-process dev runs."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            self._data[key] = data

    def get(self, key: str) -> bytes:
        with self._lock:
            if key not in self._data:
                raise ObjectStoreError("object not found")
            return self._data[key]
