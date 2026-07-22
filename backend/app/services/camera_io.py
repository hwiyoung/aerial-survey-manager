"""Persistent, validated management of the standard camera IO catalog."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.project import CameraModel, Image

settings = get_settings()
SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")


def decode_io_bytes(payload: bytes) -> tuple[str, str]:
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("io.csv uses an unsupported text encoding")


def parse_io_content(content: str) -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    current_camera: dict[str, Any] | None = None

    for row in csv.reader(content.splitlines()):
        parts = [part.strip() for part in row]
        if not parts or not any(parts):
            continue
        if parts[0] == "$CAMERA":
            if current_camera is not None:
                raise ValueError("nested $CAMERA block")
            current_camera = {}
            continue
        if parts[0] == "$END_CAMERA":
            if current_camera is None:
                raise ValueError("$END_CAMERA without $CAMERA")
            cameras.append(current_camera)
            current_camera = None
            continue
        if current_camera is None or len(parts) <= 1:
            continue

        field = parts[0] if parts[0] else parts[1]
        offset = 2 if len(parts) > 1 and field == parts[1] else 1
        if "$CAMERA_NAME:" in field and len(parts) > offset:
            current_camera["name"] = parts[offset]
        elif "$LENS_SN:" in field:
            companies = []
            for value in parts[offset:]:
                if not value or value.startswith("$"):
                    break
                companies.append(value)
            current_camera["companies"] = companies
        elif "$FOCAL_LENGTH:" in field and len(parts) > offset and parts[offset]:
            current_camera["focal_length"] = float(parts[offset])
        elif "$SENSOR_SIZE:" in field and len(parts) > offset + 1:
            current_camera["sensor_width_px"] = int(parts[offset])
            current_camera["sensor_height_px"] = int(parts[offset + 1])
        elif "$PIXEL_SIZE:" in field and len(parts) > offset and parts[offset]:
            current_camera["pixel_size"] = float(parts[offset])
        elif "$PRINCIPAL_POINT_AUTOCOLLIMATION:" in field and len(parts) > offset + 1:
            current_camera["ppa_x"] = float(parts[offset])
            current_camera["ppa_y"] = float(parts[offset + 1])

    if current_camera is not None:
        raise ValueError("$CAMERA block is not closed")
    if not cameras:
        raise ValueError("no camera blocks found")
    return cameras


def validate_io_cameras(cameras: list[dict[str, Any]]) -> None:
    for index, camera in enumerate(cameras, start=1):
        required_positive = (
            "focal_length",
            "sensor_width_px",
            "sensor_height_px",
            "pixel_size",
        )
        if not str(camera.get("name") or "").strip():
            raise ValueError(f"camera block {index} has no name")
        for field in required_positive:
            if float(camera.get(field) or 0) <= 0:
                raise ValueError(f"camera block {index} has invalid {field}")


def calculate_sensor_dimensions(camera: dict[str, Any]) -> dict[str, Any]:
    result = camera.copy()
    pixel_size = camera.get("pixel_size", 0)
    if pixel_size and camera.get("sensor_width_px"):
        result["sensor_width"] = round(camera["sensor_width_px"] * pixel_size / 1000, 2)
    if pixel_size and camera.get("sensor_height_px"):
        result["sensor_height"] = round(camera["sensor_height_px"] * pixel_size / 1000, 2)
    return result


def _name_key(name: str) -> str:
    return name.strip().casefold()


def _display_name(base_name: str, company: str, used_names: set[str]) -> str:
    candidate = f"{base_name} - {company}" if company else base_name
    if _name_key(candidate) not in used_names:
        return candidate
    suffix = 2
    while _name_key(f"{candidate} #{suffix}") in used_names:
        suffix += 1
    return f"{candidate} #{suffix}"


def create_camera_entries(cameras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for source_index, raw_camera in enumerate(cameras):
        camera = calculate_sensor_dimensions(raw_camera)
        base_name = str(camera.get("name") or "").strip()
        companies = [
            str(company).strip()
            for company in camera.get("companies", [])
            if str(company).strip()
        ]
        legacy_names = [base_name]
        if companies:
            legacy_names.append(f"{base_name} - {', '.join(companies)}")
        if len(companies) > 3:
            legacy_names.append(f"{base_name} - {', '.join(companies[:3])}")

        for company_index, company in enumerate(companies or [""]):
            name = _display_name(base_name, company, used_names)
            used_names.add(_name_key(name))
            entries.append(
                {
                    "name": name,
                    "legacy_names": legacy_names,
                    "focal_length": camera.get("focal_length"),
                    "sensor_width": camera.get("sensor_width"),
                    "sensor_height": camera.get("sensor_height"),
                    "pixel_size": camera.get("pixel_size"),
                    "sensor_width_px": camera.get("sensor_width_px"),
                    "sensor_height_px": camera.get("sensor_height_px"),
                    "ppa_x": camera.get("ppa_x"),
                    "ppa_y": camera.get("ppa_y"),
                    "is_custom": False,
                    "_source_index": source_index,
                    "_company_index": company_index,
                    "_base_name": base_name,
                    "_company": company,
                }
            )
    return entries


def parse_and_validate_io(content: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cameras = parse_io_content(content)
    validate_io_cameras(cameras)
    entries = create_camera_entries(cameras)
    if not entries:
        raise ValueError("no usable camera models found")
    return cameras, entries


def apply_camera_entry(camera_model: CameraModel, entry: dict[str, Any]) -> None:
    for field in (
        "name",
        "focal_length",
        "sensor_width",
        "sensor_height",
        "pixel_size",
        "sensor_width_px",
        "sensor_height_px",
        "ppa_x",
        "ppa_y",
    ):
        setattr(camera_model, field, entry.get(field))


async def sync_standard_camera_models(
    db: AsyncSession,
    entries: list[dict[str, Any]],
) -> dict[str, int]:
    entry_by_name = {_name_key(entry["name"]): entry for entry in entries}
    valid_names = set(entry_by_name)
    legacy_entries: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for legacy_name in entry.get("legacy_names", []):
            legacy_entries.setdefault(_name_key(legacy_name), entry)

    result = await db.execute(
        select(CameraModel).where(
            CameraModel.is_custom.is_(False),
            CameraModel.organization_id.is_(None),
        )
    )
    existing = list(result.scalars().all())
    reserved_names = {_name_key(camera.name) for camera in existing}
    deleted = 0
    migrated = 0
    retained = 0

    for camera in existing:
        camera_key = _name_key(camera.name)
        if camera_key in valid_names:
            continue
        replacement = legacy_entries.get(camera_key)
        replacement_key = _name_key(replacement["name"]) if replacement else None
        if replacement and replacement_key not in reserved_names:
            apply_camera_entry(camera, replacement)
            reserved_names.discard(camera_key)
            reserved_names.add(replacement_key)
            migrated += 1
            continue
        references = await db.scalar(
            select(func.count(Image.id)).where(Image.camera_model_id == camera.id)
        )
        if references:
            retained += 1
            continue
        await db.delete(camera)
        deleted += 1

    result = await db.execute(
        select(CameraModel).where(
            CameraModel.is_custom.is_(False),
            CameraModel.organization_id.is_(None),
        )
    )
    current = {_name_key(camera.name): camera for camera in result.scalars().all()}
    inserted = 0
    updated = 0
    for entry in entries:
        camera = current.get(_name_key(entry["name"]))
        if camera:
            apply_camera_entry(camera, entry)
            updated += 1
            continue
        db.add(
            CameraModel(
                **{key: entry.get(key) for key in (
                    "name",
                    "focal_length",
                    "sensor_width",
                    "sensor_height",
                    "pixel_size",
                    "sensor_width_px",
                    "sensor_height_px",
                    "ppa_x",
                    "ppa_y",
                )},
                is_custom=False,
                organization_id=None,
            )
        )
        inserted += 1
    await db.flush()
    return {
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "migrated": migrated,
        "retained_referenced": retained,
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def ensure_persistent_io_file() -> Path:
    config_path = Path(settings.CAMERA_IO_CONFIG_PATH)
    if config_path.is_file():
        return config_path
    source_path = Path(settings.CAMERA_IO_SOURCE_PATH)
    if not source_path.is_file():
        raise FileNotFoundError("camera IO source file is missing")
    _atomic_write(config_path, source_path.read_bytes())
    return config_path


def read_io_document() -> dict[str, Any]:
    path = ensure_persistent_io_file()
    payload = path.read_bytes()
    content, encoding = decode_io_bytes(payload)
    cameras, entries = parse_and_validate_io(content)
    backups_dir = path.parent / "backups"
    return {
        "content": content,
        "encoding": encoding,
        "sha256": sha256_bytes(payload),
        "camera_block_count": len(cameras),
        "model_count": len(entries),
        "backup_count": len(list(backups_dir.glob("io.*.csv"))) if backups_dir.exists() else 0,
    }


def prepare_io_update(content: str, expected_sha256: str) -> dict[str, Any]:
    path = ensure_persistent_io_file()
    previous = path.read_bytes()
    if sha256_bytes(previous) != expected_sha256:
        raise FileExistsError("camera IO document changed since it was loaded")
    _, encoding = decode_io_bytes(previous)
    cameras, entries = parse_and_validate_io(content)
    updated = content.encode(encoding)
    return {
        "path": path,
        "previous": previous,
        "updated": updated,
        "encoding": encoding,
        "cameras": cameras,
        "entries": entries,
    }


def _serialize_csv_row(row: list[str]) -> str:
    output = io.StringIO()
    csv.writer(output, lineterminator="").writerow(row)
    return output.getvalue()


def _replace_io_row_values(row: list[str], field: str, values: list[Any]) -> list[str]:
    try:
        field_index = row.index(field)
    except ValueError:
        return row
    required_length = field_index + 1 + len(values)
    if len(row) < required_length:
        row.extend([""] * (required_length - len(row)))
    for index, value in enumerate(values, start=field_index + 1):
        row[index] = str(value)
    return row


def update_io_camera_content(
    content: str,
    camera_model_name: str,
    values: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Update one IO camera block while preserving unrelated CSV rows."""
    cameras, entries = parse_and_validate_io(content)
    target = next(
        (entry for entry in entries if _name_key(entry["name"]) == _name_key(camera_model_name)),
        None,
    )
    if target is None:
        raise ValueError("camera model is not present in io.csv")

    requested_name = str(values.get("name") or "").strip()
    if not requested_name:
        raise ValueError("camera model name must not be empty")
    company = str(target.get("_company") or "")
    if requested_name == target["name"]:
        base_name = target["_base_name"]
    elif company and requested_name.endswith(f" - {company}"):
        base_name = requested_name[: -(len(company) + 3)].strip()
    else:
        base_name = requested_name
    if not base_name:
        raise ValueError("camera model name must not be empty")

    field_values = {
        "$CAMERA_NAME:": [base_name],
        "$FOCAL_LENGTH:": [values.get("focal_length")],
        "$PRINCIPAL_POINT_AUTOCOLLIMATION:": [values.get("ppa_x", 0), values.get("ppa_y", 0)],
        "$SENSOR_SIZE:": [values.get("sensor_width_px"), values.get("sensor_height_px")],
        "$PIXEL_SIZE:": [values.get("pixel_size"), values.get("pixel_size")],
    }
    target_source_index = int(target["_source_index"])
    current_source_index = -1
    updated_lines: list[str] = []
    for line in content.splitlines():
        row = next(csv.reader([line]))
        if row and row[0].strip() == "$CAMERA":
            current_source_index += 1
        if current_source_index == target_source_index:
            for field, replacements in field_values.items():
                if field in row:
                    row = _replace_io_row_values(row, field, replacements)
                    line = _serialize_csv_row(row)
                    break
        updated_lines.append(line)

    updated_content = "\n".join(updated_lines) + ("\n" if content.endswith(("\n", "\r")) else "")
    _, updated_entries = parse_and_validate_io(updated_content)
    updated_target = next(
        (
            entry
            for entry in updated_entries
            if entry.get("_source_index") == target_source_index
            and entry.get("_company_index") == target.get("_company_index")
        ),
        None,
    )
    if updated_target is None:
        raise ValueError("updated camera model could not be resolved")
    return updated_content, updated_target


def prepare_camera_io_model_update(
    camera_model_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Prepare an atomic io.csv update for one structured camera form."""
    document = read_io_document()
    updated_content, target_entry = update_io_camera_content(
        document["content"],
        camera_model_name,
        values,
    )
    prepared = prepare_io_update(updated_content, document["sha256"])
    prepared["target_entry"] = target_entry
    return prepared


def backup_and_replace_io(prepared: dict[str, Any]) -> Path:
    path: Path = prepared["path"]
    previous: bytes = prepared["previous"]
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = path.parent / "backups" / f"io.{timestamp}.{sha256_bytes(previous)[:12]}.csv"
    _atomic_write(backup_path, previous)
    _atomic_write(path, prepared["updated"])
    return backup_path


def restore_io(prepared: dict[str, Any]) -> None:
    _atomic_write(prepared["path"], prepared["previous"])


def cleanup_io_backups() -> int:
    path = Path(settings.CAMERA_IO_CONFIG_PATH)
    backups = sorted(
        (path.parent / "backups").glob("io.*.csv"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for backup in backups[max(1, int(settings.CAMERA_IO_BACKUP_COUNT)):]:
        backup.unlink(missing_ok=True)
        removed += 1
    return removed
