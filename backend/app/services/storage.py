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
        self.client = Minio(
            settings.MINIO_ENDPOINT,
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
        Generate a presigned URL for downloading.
        
        Args:
            object_name: Object name/key in storage
            expires: Expiration time in seconds
            response_headers: Optional response headers to include
        
        Returns:
            Presigned URL
        """
        return self.client.presigned_get_object(
            self.bucket,
            object_name,
            expires=timedelta(seconds=expires),
            response_headers=response_headers,
        )
    
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


# Global storage service instance
storage_service = StorageService()


def get_storage() -> StorageService:
    """Get the storage service instance."""
    return storage_service
