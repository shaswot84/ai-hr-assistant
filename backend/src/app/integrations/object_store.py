from __future__ import annotations

import io
import uuid

from minio import Minio
from minio.error import S3Error

from app.config.settings import get_settings


class ObjectStore:
    """S3-compatible object store (MinIO in dev). Authoritative bytes for resumes."""

    def __init__(self) -> None:
        """Configure the MinIO client and target bucket from app settings."""
        settings = get_settings()
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket

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
            io.BytesIO(data),
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
