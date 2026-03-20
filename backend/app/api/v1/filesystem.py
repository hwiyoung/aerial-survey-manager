"""Filesystem browsing API for server-side directory navigation."""
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.models.user import User
from app.auth.jwt import get_current_user

router = APIRouter(prefix="/filesystem", tags=["Filesystem"])

# Image extensions recognised by the browser
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}

# EO / text file extensions
EO_EXTENSIONS = {".txt", ".csv", ".json"}

# File type presets for browse API
FILE_TYPE_PRESETS = {
    "images": IMAGE_EXTENSIONS,
    "eo": EO_EXTENSIONS,
}

# Allowed root paths for browsing (host-mounted directories only)
ALLOWED_ROOTS = ["/media", "/mnt", "/run/media", "/home"]

# Depth to scan for device-level directories
# /media/<user>/<device> = 2, /run/media/<user>/<device> = 2
# /mnt 제외: 수동 마운트 전용이라 일반 사용자에게 불필요
SCAN_DEPTHS = {"/media": 2, "/run/media": 2, "/home": 1}

# Skip system mounts (snap, loop, etc.)
SKIP_PREFIXES = ("snap-", "loop", ".")


def _is_within_allowed_root(path: str) -> bool:
    """Check if a path is within an allowed root directory."""
    resolved = str(Path(path).resolve())
    return any(
        resolved == root or resolved.startswith(root + "/")
        for root in ALLOWED_ROOTS
    )


def _get_disk_usage(path: str) -> tuple:
    """Get disk usage in GB. Returns (total_gb, used_gb) or (None, None)."""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        used = total - (stat.f_bavail * stat.f_frsize)
        return round(total / (1024**3), 1), round(used / (1024**3), 1)
    except (OSError, PermissionError):
        return None, None


def _enumerate_devices(root: str, depth: int) -> List[Path]:
    """Enumerate device-level directories under a root path."""
    devices = []
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        return devices

    try:
        if depth == 1:
            for child in root_path.iterdir():
                if child.name.startswith(SKIP_PREFIXES):
                    continue
                if child.is_dir():
                    devices.append(child)
        elif depth == 2:
            for user_dir in root_path.iterdir():
                if user_dir.name.startswith(".") or not user_dir.is_dir():
                    continue
                try:
                    for device in user_dir.iterdir():
                        if device.name.startswith(SKIP_PREFIXES):
                            continue
                        if device.is_dir():
                            devices.append(device)
                except PermissionError:
                    continue
    except PermissionError:
        pass

    return devices


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None
    modified: Optional[float] = None


class BrowseResponse(BaseModel):
    current_path: str
    parent_path: Optional[str] = None
    entries: List[FileEntry]
    image_count: int = 0


class RootEntry(BaseModel):
    name: str
    path: str
    has_contents: bool
    total_gb: Optional[float] = None
    used_gb: Optional[float] = None


class RootsResponse(BaseModel):
    roots: List[RootEntry]
    hint: str = "외장하드가 보이지 않으면 USB를 다시 연결한 후 새로고침 해주세요"


@router.get("/roots", response_model=RootsResponse)
async def get_filesystem_roots(
    current_user: User = Depends(get_current_user),
):
    """List mounted devices/volumes available for browsing."""
    roots = []
    for root, depth in SCAN_DEPTHS.items():
        for device_path in _enumerate_devices(root, depth):
            try:
                has_contents = any(
                    not c.name.startswith(".")
                    for c in device_path.iterdir()
                )
            except PermissionError:
                has_contents = False

            total_gb, used_gb = _get_disk_usage(str(device_path))
            roots.append(RootEntry(
                name=device_path.name,
                path=str(device_path),
                has_contents=has_contents,
                total_gb=total_gb,
                used_gb=used_gb,
            ))

    roots.sort(key=lambda r: r.name.lower())
    return RootsResponse(roots=roots)


@router.get("/browse", response_model=BrowseResponse)
async def browse_filesystem(
    path: str = Query("/", description="Absolute directory path to browse"),
    file_types: str = Query("images", description="File type preset: 'images' or 'eo'"),
    current_user: User = Depends(get_current_user),
):
    """Browse the server filesystem and return directory contents.

    Only directories and files matching the requested type preset are returned.
    Entries are sorted: directories first, then files, alphabetically.
    Browsing is restricted to allowed root paths.
    """
    # Normalise and validate the requested path
    target = Path(path).resolve()

    # Security: restrict to allowed roots
    if not _is_within_allowed_root(str(target)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: path is outside allowed directories ({', '.join(ALLOWED_ROOTS)})",
        )

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path does not exist: {path}",
        )

    if not target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {path}",
        )

    # Prevent path traversal via '..'
    if ".." in Path(path).parts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Path traversal is not allowed",
        )

    # Resolve allowed extensions from the file_types preset
    allowed_extensions = FILE_TYPE_PRESETS.get(file_types, IMAGE_EXTENSIONS)

    entries: List[FileEntry] = []
    image_count = 0

    try:
        for entry in os.scandir(str(target)):
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except (PermissionError, OSError):
                continue

            if entry.name.startswith("."):
                continue

            if entry.is_dir(follow_symlinks=False):
                entries.append(
                    FileEntry(
                        name=entry.name,
                        path=str(Path(entry.path).resolve()),
                        is_dir=True,
                        size=None,
                        modified=entry_stat.st_mtime,
                    )
                )
            elif entry.is_file(follow_symlinks=False):
                ext = Path(entry.name).suffix.lower()
                if ext in allowed_extensions:
                    image_count += 1
                    entries.append(
                        FileEntry(
                            name=entry.name,
                            path=str(Path(entry.path).resolve()),
                            is_dir=False,
                            size=entry_stat.st_size,
                            modified=entry_stat.st_mtime,
                        )
                    )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {path}",
        )

    # Sort: directories first, then files, alphabetically within each group
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

    # Determine parent path (only if still within allowed roots)
    parent = str(target.parent)
    parent_path = parent if _is_within_allowed_root(parent) else None

    return BrowseResponse(
        current_path=str(target),
        parent_path=parent_path,
        entries=entries,
        image_count=image_count,
    )


class ReadTextResponse(BaseModel):
    content: str
    filename: str
    size: int


# Maximum file size for read-text: 10 MB
MAX_READ_TEXT_SIZE = 10 * 1024 * 1024


@router.get("/read-text", response_model=ReadTextResponse)
async def read_text_file(
    path: str = Query(..., description="Absolute path to a text file"),
    current_user: User = Depends(get_current_user),
):
    """Read the contents of a text file on the server.

    Restricted to allowed root paths and recognised text extensions.
    Maximum file size: 10 MB.
    """
    target = Path(path).resolve()

    if not _is_within_allowed_root(str(target)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path is outside allowed directories",
        )

    if ".." in Path(path).parts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Path traversal is not allowed",
        )

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path}",
        )

    ext = target.suffix.lower()
    if ext not in EO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(EO_EXTENSIONS))}",
        )

    file_size = target.stat().st_size
    if file_size > MAX_READ_TEXT_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: {file_size} bytes (max {MAX_READ_TEXT_SIZE})",
        )

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = target.read_text(encoding="cp949")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to read file: unsupported encoding",
            )

    return ReadTextResponse(
        content=content,
        filename=target.name,
        size=file_size,
    )
