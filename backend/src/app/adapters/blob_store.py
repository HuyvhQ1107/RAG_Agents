"""LocalBlobStore and S3BlobStore adapters keyed by document_version_id (T020)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings


class LocalBlobStore:
    """Filesystem blob store under BLOB_STORE_LOCAL_DIR."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        raw_dir = base_dir or get_settings().blob_store_local_dir
        self.base_dir = Path(raw_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        safe_key = key.lstrip("/\\").replace("..", "_")
        target = (self.base_dir / safe_key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._resolve(key)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"Blob not found: {key}")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()


class S3BlobStore:
    """S3-compatible (MinIO / S3) blob store adapter."""

    def __init__(self, client: Any = None, bucket: str | None = None) -> None:
        settings = get_settings()
        self.bucket = bucket or settings.s3_bucket
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3

            settings = get_settings()
            self._client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url)
        return self._client

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._get_client().put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )
        return key

    async def get(self, key: str) -> bytes:
        resp = self._get_client().get_object(Bucket=self.bucket, Key=key)
        return bytes(resp["Body"].read())

    async def delete(self, key: str) -> None:
        self._get_client().delete_object(Bucket=self.bucket, Key=key)
