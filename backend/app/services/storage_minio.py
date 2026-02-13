"""MinIO/S3 storage backend implementation."""
from datetime import timedelta
from typing import Optional
import io

from minio import Minio
from minio.error import S3Error

from app.config import get_settings
from app.services.storage_base import StorageBackend

settings = get_settings()


class MinIOStorageBackend(StorageBackend):
    """Storage backend using MinIO/S3."""

    def __init__(self):
        # Internal client for actual S3 operations (upload, download, delete)
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

        # Separate client for presigned URL generation using PUBLIC endpoint
        # AWS S3 V4 signature includes the Host header, so we must generate
        # presigned URLs with the correct public endpoint from the start
        public_endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
        self.presigned_client = Minio(
            public_endpoint,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

        self.bucket = settings.MINIO_BUCKET
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Ensure the bucket exists."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as e:
            print(f"Error ensuring bucket: {e}")

    def upload_file(
        self,
        local_path: str,
        object_name: str,
        content_type: Optional[str] = None,
    ) -> str:
        self.client.fput_object(
            self.bucket,
            object_name,
            local_path,
            content_type=content_type,
        )
        return object_name

    def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        content_type: Optional[str] = None,
    ) -> str:
        self.client.put_object(
            self.bucket,
            object_name,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )
        return object_name

    def download_file(self, object_name: str, local_path: str) -> str:
        self.client.fget_object(self.bucket, object_name, local_path)
        return local_path

    def get_presigned_url(
        self,
        object_name: str,
        expires: int = 3600,
        response_headers: Optional[dict] = None,
    ) -> str:
        # Objects under projects/ are publicly accessible (bucket policy set)
        # Use nginx /storage/ proxy to avoid exposing MinIO port directly
        if object_name.startswith("projects/"):
            return f"/storage/{object_name}"

        # For private objects, generate presigned URL via nginx proxy
        protocol = "https" if settings.MINIO_SECURE else "http"
        public_endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT

        url = self.client.presigned_get_object(
            self.bucket,
            object_name,
            expires=timedelta(seconds=expires),
            response_headers=response_headers,
        )

        # Replace internal endpoint with public endpoint for browser access
        if public_endpoint and public_endpoint != settings.MINIO_ENDPOINT:
            internal_endpoint = settings.MINIO_ENDPOINT
            url = url.replace(f"http://{internal_endpoint}", f"{protocol}://{public_endpoint}")
            url = url.replace(f"https://{internal_endpoint}", f"{protocol}://{public_endpoint}")

        return url

    def get_presigned_upload_url(
        self,
        object_name: str,
        expires: int = 3600,
    ) -> Optional[str]:
        return self.client.presigned_put_object(
            self.bucket,
            object_name,
            expires=timedelta(seconds=expires),
        )

    def delete_object(self, object_name: str) -> None:
        self.client.remove_object(self.bucket, object_name)

    def object_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False

    def get_object_size(self, object_name: str) -> int:
        stat = self.client.stat_object(self.bucket, object_name)
        return stat.size

    def list_objects(self, prefix: str = "", recursive: bool = True) -> list[str]:
        objects = self.client.list_objects(
            self.bucket,
            prefix=prefix,
            recursive=recursive,
        )
        return [obj.object_name for obj in objects]

    def delete_recursive(self, prefix: str) -> None:
        from minio.deleteobjects import DeleteObject
        objects = self.list_objects(prefix=prefix, recursive=True)
        if not objects:
            return

        delete_list = [DeleteObject(obj) for obj in objects]
        for errors in self.client.remove_objects(self.bucket, delete_list):
            for error in errors:
                print(f"Error deleting object {error.object_name}: {error}")
