"""Authenticated and capability-scoped project file serving."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.user import User
from app.auth.jwt import PermissionChecker, get_current_user
from app.database import get_db
from app.services.asset_tokens import verify_asset_token
from app.services.storage import get_storage

router = APIRouter(prefix="/storage", tags=["Storage"])


def _project_id_from_storage_key(path: str) -> UUID | None:
    parts = Path(path).parts
    if len(parts) < 3 or parts[0] not in {"projects", "orthomosaic"}:
        return None
    try:
        return UUID(parts[1])
    except ValueError:
        return None


@router.get("/assets/{token}")
async def serve_project_asset(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve a short-lived project preview capability."""
    try:
        payload = verify_asset_token(token, purpose="preview")
        project_id = UUID(payload["project_id"])
        object_name = str(payload["object_name"])
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    if ".." in object_name or object_name.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    encoded_project_id = _project_id_from_storage_key(object_name)
    is_current_project_artifact = object_name in {
        project.ortho_path,
        project.ortho_thumbnail_path,
    }
    if encoded_project_id != project_id and not is_current_project_artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    storage = get_storage()
    if not storage.object_exists(object_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    local_path = storage.get_local_path(object_name)
    if local_path and Path(local_path).exists():
        response = FileResponse(local_path)
        response.headers["Cache-Control"] = "private, max-age=900"
        return response

    signed_url = storage.get_presigned_url(object_name, expires=900)
    response = RedirectResponse(signed_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/files/{path:path}")
async def serve_storage_file(
    path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve a file from local storage (authenticated).

    Only used in local storage mode for private files.
    Project paths are additionally checked against project permissions.
    """
    # Reject obvious path traversal attempts early
    if ".." in path or path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Project files require permission on the project encoded in the key.
    path_parts = Path(path).parts
    if path_parts and path_parts[0] in {"projects", "orthomosaic"}:
        project_id = _project_id_from_storage_key(path)
        if project_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        permission_checker = PermissionChecker("view")
        if not await permission_checker.check(str(project_id), current_user, db):
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
