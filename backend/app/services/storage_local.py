"""Local filesystem storage backend implementation.

Stores files on local disk using the same key structure as MinIO.
Used for single-server deployments where MinIO overhead is unnecessary.
"""
import os
import shutil
from pathlib import Path
from typing import Optional

from app.services.storage_base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """Storage backend using local filesystem."""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_name: str) -> Path:
        """Resolve object name to absolute path with path traversal protection."""
        # Empty string = base path (used for storage detection and list_objects)
        if object_name == "":
            return self.base_path.resolve()
        if not object_name or object_name.startswith("/"):
            raise ValueError(f"Invalid object name: {object_name}")
        target = (self.base_path / object_name).resolve()
        if not target.is_relative_to(self.base_path.resolve()):
            raise ValueError(f"Path traversal detected: {object_name}")
        return target

    def upload_file(
        self,
        local_path: str,
        object_name: str,
        content_type: Optional[str] = None,
    ) -> str:
        dest = self._resolve(object_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # If source and dest are the same, skip copy
        if Path(local_path).resolve() != dest.resolve():
            shutil.copy2(local_path, dest)
        return object_name

    def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        content_type: Optional[str] = None,
    ) -> str:
        dest = self._resolve(object_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return object_name

    def download_file(self, object_name: str, local_path: str) -> str:
        src = self._resolve(object_name)
        if not src.exists():
            raise FileNotFoundError(f"Object not found: {object_name}")
        dest = Path(local_path)
        # If source and dest are the same, skip copy
        if src.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        return local_path

    def get_presigned_url(
        self,
        object_name: str,
        expires: int = 3600,
        response_headers: Optional[dict] = None,
    ) -> str:
        # Public paths (projects/) are served by nginx /storage/ alias
        if object_name.startswith("projects/"):
            return f"/storage/{object_name}"
        # Private paths served via authenticated API endpoint
        return f"/api/v1/storage/files/{object_name}"

    def get_presigned_upload_url(
        self,
        object_name: str,
        expires: int = 3600,
    ) -> Optional[str]:
        # Local mode doesn't support presigned upload URLs
        return None

    def delete_object(self, object_name: str) -> None:
        path = self._resolve(object_name)
        if path.exists():
            path.unlink()

    def object_exists(self, object_name: str) -> bool:
        return self._resolve(object_name).exists()

    def get_object_size(self, object_name: str) -> int:
        path = self._resolve(object_name)
        if not path.exists():
            raise FileNotFoundError(f"Object not found: {object_name}")
        return path.stat().st_size

    def list_objects(self, prefix: str = "", recursive: bool = True) -> list[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []

        results = []
        if base.is_file():
            # Prefix matches a single file
            return [prefix]

        iterator = base.rglob("*") if recursive else base.glob("*")
        for p in iterator:
            if p.is_file():
                results.append(str(p.relative_to(self.base_path)))
        return sorted(results)

    def delete_recursive(self, prefix: str) -> None:
        path = self._resolve(prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)

    def get_local_path(self, object_name: str) -> Optional[str]:
        """Return local filesystem path for direct access."""
        path = self._resolve(object_name)
        if path.exists():
            return str(path)
        # Return the expected path even if file doesn't exist yet
        # (used for determining local mode)
        return str(path)

    def move_file(self, local_path: str, object_name: str) -> str:
        """Move a file into storage (no copy, just rename/move).

        More efficient than upload_file for large files on the same filesystem.
        """
        dest = self._resolve(object_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if Path(local_path).resolve() != dest.resolve():
            shutil.move(local_path, str(dest))
        return object_name
