"""MinIO/S3 storage service."""
from datetime import timedelta
from pathlib import Path
from typing import Optional
import io
import os

from minio import Minio
from minio.error import S3Error

from app.config import get_settings

settings = get_settings()


class StorageService:
    """Service for interacting with MinIO/S3 storage."""
    
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
        """
        Upload a file to storage.
        
        Args:
            local_path: Local file path to upload
            object_name: Object name/key in storage
            content_type: MIME type of the file
        
        Returns:
            The object name/key
        """
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
        """Upload bytes to storage."""
        self.client.put_object(
            self.bucket,
            object_name,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )
        return object_name
    
    def download_file(self, object_name: str, local_path: str) -> str:
        """
        Download a file from storage.
        
        Args:
            object_name: Object name/key in storage
            local_path: Local path to save the file
        
        Returns:
            The local file path
        """
        self.client.fget_object(self.bucket, object_name, local_path)
        return local_path
    
    def get_presigned_url(
        self,
        object_name: str,
        expires: int = 3600,
        response_headers: Optional[dict] = None,
    ) -> str:
        """
        Generate a URL for downloading.

        For public paths (projects/), returns a simple public URL via direct MinIO access.
        For private paths, generates a presigned URL via nginx proxy.

        Args:
            object_name: Object name/key in storage
            expires: Expiration time in seconds
            response_headers: Optional response headers to include

        Returns:
            URL accessible from browser
        """
        protocol = "https" if settings.MINIO_SECURE else "http"

        # Objects under projects/ are publicly accessible (bucket policy set)
        # Use direct MinIO access (port 9002) to avoid signature issues
        if object_name.startswith("projects/"):
            # MINIO_PUBLIC_ENDPOINT is for nginx proxy (uploads)
            # For direct public access, use the same host but port 9002
            public_endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
            # Extract host from endpoint and use direct MinIO port
            host = public_endpoint.split(':')[0]
            direct_endpoint = f"{host}:9002"
            return f"{protocol}://{direct_endpoint}/{self.bucket}/{object_name}"

        # For private objects, generate presigned URL via nginx proxy
        public_endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT

        # For private objects, generate presigned URL using internal client
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
    ) -> str:
        """
        Generate a presigned URL for uploading.
        
        Args:
            object_name: Object name/key in storage
            expires: Expiration time in seconds
        
        Returns:
            Presigned URL for PUT request
        """
        return self.client.presigned_put_object(
            self.bucket,
            object_name,
            expires=timedelta(seconds=expires),
        )
    
    def delete_object(self, object_name: str) -> None:
        """Delete an object from storage."""
        self.client.remove_object(self.bucket, object_name)
    
    def object_exists(self, object_name: str) -> bool:
        """Check if an object exists in storage."""
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False
    
    def get_object_size(self, object_name: str) -> int:
        """Get the size of an object in bytes."""
        stat = self.client.stat_object(self.bucket, object_name)
        return stat.size
    
    def list_objects(self, prefix: str = "", recursive: bool = True) -> list[str]:
        """List objects with a given prefix."""
        objects = self.client.list_objects(
            self.bucket,
            prefix=prefix,
            recursive=recursive,
        )
        return [obj.object_name for obj in objects]
    
    def delete_recursive(self, prefix: str) -> None:
        """Delete all objects with a given prefix."""
        from minio.deleteobjects import DeleteObject
        objects = self.list_objects(prefix=prefix, recursive=True)
        if not objects:
            return
        
        delete_list = [DeleteObject(obj) for obj in objects]
        for errors in self.client.remove_objects(self.bucket, delete_list):
            for error in errors:
                print(f"Error deleting object {error.object_name}: {error}")


# Global storage service instance
storage_service = StorageService()


def get_storage() -> StorageService:
    """Get the storage service instance."""
    return storage_service
