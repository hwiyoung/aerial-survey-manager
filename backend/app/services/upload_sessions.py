"""Validation and durable metadata for multipart upload sessions."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from uuid import UUID


MIN_MULTIPART_PART_SIZE = 5 * 1024 * 1024
MAX_MULTIPART_PART_SIZE = 512 * 1024 * 1024
MAX_MULTIPART_PARTS = 10_000
MAX_UPLOAD_FILES_PER_REQUEST = 5_000
MAX_TOTAL_MULTIPART_PARTS_PER_REQUEST = 50_000
SESSION_METADATA_FILENAME = "session.json"


class UploadSessionError(ValueError):
    """Raised when upload metadata or client input is unsafe/inconsistent."""


def normalize_upload_filename(filename: str) -> str:
    raw = str(filename or "").strip()
    if (
        not raw
        or len(raw) > 255
        or raw.startswith(".")
        or "/" in raw
        or "\\" in raw
        or ".." in raw
        or os.path.basename(raw) != raw
    ):
        raise UploadSessionError(f"Invalid filename: {filename}")
    return raw


def multipart_part_count(file_size: int, part_size: int) -> int:
    if file_size <= 0:
        raise UploadSessionError("File size must be greater than zero.")
    if not MIN_MULTIPART_PART_SIZE <= part_size <= MAX_MULTIPART_PART_SIZE:
        raise UploadSessionError(
            "part_size must be between "
            f"{MIN_MULTIPART_PART_SIZE} and {MAX_MULTIPART_PART_SIZE} bytes."
        )
    count = math.ceil(file_size / part_size)
    if count > MAX_MULTIPART_PARTS:
        raise UploadSessionError(
            f"Upload requires {count} parts; maximum is {MAX_MULTIPART_PARTS}. "
            "Increase part_size."
        )
    return count


def expected_part_size(file_size: int, part_size: int, part_number: int) -> int:
    count = multipart_part_count(file_size, part_size)
    if part_number < 1 or part_number > count:
        raise UploadSessionError(
            f"Part number {part_number} is outside the expected range 1..{count}."
        )
    if part_number < count:
        return part_size
    return file_size - (part_size * (count - 1))


def validate_upload_batch(
    files: Iterable[object],
    part_size: int,
    max_file_size: int,
) -> list[str]:
    file_list = list(files)
    if not file_list:
        raise UploadSessionError("At least one file is required.")
    if len(file_list) > MAX_UPLOAD_FILES_PER_REQUEST:
        raise UploadSessionError(
            f"At most {MAX_UPLOAD_FILES_PER_REQUEST} files can be initialized at once."
        )

    safe_names: list[str] = []
    seen: set[str] = set()
    total_parts = 0
    for file_info in file_list:
        filename = normalize_upload_filename(getattr(file_info, "filename", ""))
        file_size = int(getattr(file_info, "size", 0))
        if file_size > max_file_size:
            raise UploadSessionError(
                f"File exceeds the configured maximum size: {filename}"
            )
        total_parts += multipart_part_count(file_size, part_size)
        if total_parts > MAX_TOTAL_MULTIPART_PARTS_PER_REQUEST:
            raise UploadSessionError(
                "Upload request would create too many multipart URLs; "
                "split the files into smaller batches or increase part_size."
            )
        if filename in seen:
            raise UploadSessionError(f"Duplicate filename in upload request: {filename}")
        seen.add(filename)
        safe_names.append(filename)
    return safe_names


def nonreplaceable_upload_filenames(existing_uploads: Iterable[object]) -> list[str]:
    """Return completed filenames that must not be overwritten by a new session."""
    return sorted(
        {
            str(getattr(upload, "filename", ""))
            for upload in existing_uploads
            if getattr(upload, "upload_status", None) == "completed"
            and getattr(upload, "filename", None)
        }
    )


def validate_completed_part_numbers(part_numbers: Iterable[int]) -> list[int]:
    numbers = sorted(part_numbers)
    if not numbers:
        raise UploadSessionError("No completed upload parts were provided.")
    if len(numbers) > MAX_MULTIPART_PARTS:
        raise UploadSessionError("Too many completed upload parts were provided.")
    if len(numbers) != len(set(numbers)):
        raise UploadSessionError("Duplicate completed part numbers were provided.")
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        raise UploadSessionError("Completed part numbers must be contiguous from 1.")
    return numbers


@dataclass(frozen=True)
class LocalUploadSession:
    upload_id: str
    project_id: str
    image_id: str
    filename: str
    object_key: str
    file_size: int
    part_size: int
    part_count: int

    def validate(self) -> None:
        UUID(self.upload_id)
        UUID(self.project_id)
        UUID(self.image_id)
        normalize_upload_filename(self.filename)
        expected_count = multipart_part_count(self.file_size, self.part_size)
        if self.part_count != expected_count:
            raise UploadSessionError("Upload session part count is inconsistent.")


def save_local_upload_session(staging_dir: Path, session: LocalUploadSession) -> None:
    session.validate()
    staging_dir.mkdir(parents=True, exist_ok=False)
    metadata_path = staging_dir / SESSION_METADATA_FILENAME
    temporary_path = staging_dir / f".{SESSION_METADATA_FILENAME}.tmp"
    temporary_path.write_text(
        json.dumps(asdict(session), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(metadata_path)


def load_local_upload_session(staging_dir: Path) -> LocalUploadSession:
    metadata_path = staging_dir / SESSION_METADATA_FILENAME
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        session = LocalUploadSession(**raw)
        session.validate()
        return session
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise UploadSessionError("Upload session metadata is missing or invalid.") from exc
