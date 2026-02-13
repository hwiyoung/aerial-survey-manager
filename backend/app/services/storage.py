"""Storage service factory.

Provides get_storage() which returns the active StorageBackend instance
based on STORAGE_BACKEND config ("minio" or "local").

Usage:
    from app.services.storage import get_storage
    storage = get_storage()
    storage.upload_file(...)
"""
import threading

from app.services.storage_base import StorageBackend

_storage_instance: StorageBackend | None = None
_storage_lock = threading.Lock()


def get_storage() -> StorageBackend:
    """Get the singleton storage backend instance (thread-safe)."""
    global _storage_instance
    if _storage_instance is None:
        with _storage_lock:
            if _storage_instance is None:
                from app.config import get_settings
                settings = get_settings()

                backend = settings.STORAGE_BACKEND
                if backend == "local":
                    from app.services.storage_local import LocalStorageBackend
                    _storage_instance = LocalStorageBackend(settings.LOCAL_STORAGE_PATH)
                elif backend == "minio":
                    from app.services.storage_minio import MinIOStorageBackend
                    _storage_instance = MinIOStorageBackend()
                else:
                    raise ValueError(
                        f"Invalid STORAGE_BACKEND: '{backend}'. Must be 'local' or 'minio'."
                    )

    return _storage_instance


# Backward compatibility: StorageService is now MinIOStorageBackend
# Consumers should migrate to get_storage() instead
def StorageService():
    """Deprecated: use get_storage() instead."""
    return get_storage()
