"""Local storage file serving endpoint.

Serves private files (e.g. uploaded images) from local storage
when STORAGE_BACKEND=local. Public files (projects/*) are served
directly by nginx.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pathlib import Path

from app.models.user import User
from app.auth.jwt import get_current_user
from app.services.storage import get_storage

router = APIRouter(prefix="/storage", tags=["Storage"])


@router.get("/files/{path:path}")
async def serve_storage_file(
    path: str,
    current_user: User = Depends(get_current_user),
):
    """Serve a file from local storage (authenticated).

    Only used in local storage mode for private files.
    Public files (projects/*) are served by nginx directly.
    """
    # Reject obvious path traversal attempts early
    if ".." in path or path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    storage = get_storage()

    # This endpoint is only for local storage mode
    if not hasattr(storage, "base_path"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    local_path = storage.get_local_path(path)

    if not local_path or not Path(local_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    # Security: verify resolved path is within storage base
    resolved = Path(local_path).resolve()
    if not resolved.is_relative_to(Path(storage.base_path).resolve()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return FileResponse(local_path)
