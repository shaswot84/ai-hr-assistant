"""DocumentStore abstraction over MinIO (S3-compatible object storage).

The ingestion pipeline stores the authoritative original bytes of every
uploaded document in MinIO and never couples to it directly — callers depend
on the :class:`ObjectStore` protocol. :class:`S3ObjectStore` wraps the
synchronous ``minio`` client and offloads blocking I/O with
``asyncio.to_thread`` so it is safe inside the async worker/API.

MinIO is replaceable by any S3-compatible store behind this adapter (per
``docker_infrastructure.md`` §17).

The recruitment stack stores resumes through the same bucket but needs a
plain synchronous client instead (its routes are sync `def` handlers running
in FastAPI's threadpool, not async) — see :class:`SyncS3ObjectStore` below.
"""

from __future__ import annotations

import asyncio
import uuid
from io import BytesIO
from typing import Protocol

from minio import Minio
from minio.error import S3Error

from app.config.settings import MinioSettings, get_settings


class ObjectStoreError(Exception):
    """Raised when object storage read/write fails.

    The worker maps this to ``ingestion_job.failure_reason = STORAGE_ERROR``.
    """


class ObjectStore(Protocol):
    """Minimal async object-store surface the ingestion pipeline needs."""

    async def put_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def delete_bytes(self, key: str) -> None: ...


class S3ObjectStore:
    """MinIO-backed :class:`ObjectStore`.

    The bucket is created lazily on the first write (idempotent), so no
    external provisioning step is required for local development.
    """

    def __init__(self, settings: MinioSettings | None = None) -> None:
        settings = settings or get_settings().minio
        self._bucket = settings.bucket
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        self._bucket_ready = False

    async def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        exists = await asyncio.to_thread(self._client.bucket_exists, self._bucket)
        if not exists:
            await asyncio.to_thread(self._client.make_bucket, self._bucket)
        self._bucket_ready = True

    async def put_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        await self._ensure_bucket()
        try:
            await asyncio.to_thread(
                self._client.put_object,
                self._bucket,
                key,
                BytesIO(data),
                len(data),
                content_type=content_type or "application/octet-stream",
            )
        except S3Error as exc:
            raise ObjectStoreError(f"s3 put '{key}': {exc}") from exc

    async def get_bytes(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(self._client.get_object, self._bucket, key)
        except S3Error as exc:
            raise ObjectStoreError(f"s3 get '{key}': {exc}") from exc
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def delete_bytes(self, key: str) -> None:
        """Remove an object. Missing objects are treated as success (idempotent)."""
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, key)
        except S3Error as exc:
            raise ObjectStoreError(f"s3 delete '{key}': {exc}") from exc


class SyncS3ObjectStore:
    """Synchronous MinIO client for the recruitment stack (resume upload/download).

    Recruitment's routes are plain `def` handlers (FastAPI runs them in its
    threadpool), so there's no event loop to offload onto — a blocking
    `minio` client is simpler and correct here, unlike the async
    :class:`S3ObjectStore` the ingestion pipeline needs.
    """

    def __init__(self) -> None:
        """Configure the MinIO client and target bucket from app settings."""
        settings = get_settings()
        self._client = Minio(
            settings.minio.endpoint,
            access_key=settings.minio.access_key,
            secret_key=settings.minio.secret_key,
            secure=settings.minio.secure,
        )
        self._bucket = settings.minio.bucket

    def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put_resume(self, data: bytes, filename: str, content_type: str) -> str:
        """Store resume bytes; returns the object key. Raises on failure."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
        object_key = f"resumes/{uuid.uuid4()}.{ext}"
        self._client.put_object(
            self._bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return object_key

    def get_object(self, object_key: str) -> tuple[bytes, str]:
        """Fetch object bytes + content type. Raises FileNotFoundError-style error if missing."""
        try:
            response = self._client.get_object(self._bucket, object_key)
            data = response.read()
            content_type = response.headers.get("content-type", "application/octet-stream")
        except S3Error as err:
            raise FileNotFoundError(object_key) from err
        finally:
            response.close()
            response.release_conn()
        return data, content_type
