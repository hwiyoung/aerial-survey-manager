"""Storage backend abstract base class.

Defines the interface for all storage backends (MinIO, local filesystem, etc.).
Consumers should use get_storage() from storage.py to get the active backend.
"""
from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def upload_file(
        self,
        local_path: str,
        object_name: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload a file to storage.

        Args:
            local_path: Local file path to upload
            object_name: Object name/key in storage
            content_type: MIME type of the file

        Returns:
            The object name/key
        """
        ...

    @abstractmethod
    def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload bytes to storage."""
        ...

    @abstractmethod
    def download_file(self, object_name: str, local_path: str) -> str:
        """Download a file from storage.

        Args:
            object_name: Object name/key in storage
            local_path: Local path to save the file

        Returns:
            The local file path
        """
        ...

    @abstractmethod
    def get_presigned_url(
        self,
        object_name: str,
        expires: int = 3600,
        response_headers: Optional[dict] = None,
    ) -> str:
        """Generate a URL for downloading.

        For public paths (projects/), returns a relative URL via nginx proxy.
        For private paths, generates a presigned or authenticated URL.
        """
        ...

    @abstractmethod
    def get_presigned_upload_url(
        self,
        object_name: str,
        expires: int = 3600,
    ) -> Optional[str]:
        """Generate a presigned URL for uploading.

        Returns None if direct upload URLs are not supported (e.g. local mode).
        """
        ...

    @abstractmethod
    def delete_object(self, object_name: str) -> None:
        """Delete an object from storage."""
        ...

    @abstractmethod
    def object_exists(self, object_name: str) -> bool:
        """Check if an object exists in storage."""
        ...

    @abstractmethod
    def get_object_size(self, object_name: str) -> int:
        """Get the size of an object in bytes."""
        ...

    @abstractmethod
    def list_objects(self, prefix: str = "", recursive: bool = True) -> list[str]:
        """List objects with a given prefix."""
        ...

    @abstractmethod
    def delete_recursive(self, prefix: str) -> None:
        """Delete all objects with a given prefix."""
        ...

    def get_local_path(self, object_name: str) -> Optional[str]:
        """Return local filesystem path if file is locally accessible.

        Used by processing pipeline to skip download/upload when files
        are already on local disk.

        Returns:
            Absolute file path if locally accessible, None otherwise.
        """
        return None
