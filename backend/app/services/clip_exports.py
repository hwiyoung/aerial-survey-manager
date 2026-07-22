"""Core utilities for one-file union sheet clip exports."""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from app.config import get_settings


settings = get_settings()

FORMAT_SPECS = {
    "GeoTiff": {
        "extension": ".tif",
        "driver": "COG",
        "media_type": "image/tiff",
        "creation_options": ["COMPRESS=LZW", "BIGTIFF=IF_SAFER"],
    },
    "JPG": {
        "extension": ".jpg",
        "driver": "JPEG",
        "media_type": "image/jpeg",
        "creation_options": ["QUALITY=90"],
    },
    "PNG": {
        "extension": ".png",
        "driver": "PNG",
        "media_type": "image/png",
        "creation_options": [],
    },
    "ECW": {
        "extension": ".ecw",
        "driver": "ECW",
        "media_type": "image/ecw",
        "creation_options": ["TARGET=90"],
    },
}


class ClipExportCancelled(Exception):
    """Raised when a persisted job cancellation is observed."""


class InvalidCogSource(Exception):
    """Raised when a source is readable but is not an actual COG."""


def normalize_export_format(value: str) -> str:
    aliases = {
        "geotiff": "GeoTiff",
        "gtiff": "GeoTiff",
        "tif": "GeoTiff",
        "tiff": "GeoTiff",
        "jpg": "JPG",
        "jpeg": "JPG",
        "png": "PNG",
        "ecw": "ECW",
    }
    normalized = aliases.get(str(value or "").strip().lower())
    if not normalized:
        raise ValueError("unsupported export format")
    return normalized


def make_clip_filename(base_filename: str, output_format: str) -> str:
    """Return a safe filename that always records the clip operation."""

    normalized_format = normalize_export_format(output_format)
    extension = FORMAT_SPECS[normalized_format]["extension"]
    name = Path(str(base_filename or "export").strip()).name
    name = re.sub(r"\.(?:tiff?|jpe?g|png|ecw|zip)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("._-")
    name = name[:140] or "export"
    if not name.lower().endswith("_clip"):
        name += "_clip"
    return f"{name}{extension}"


def build_cutline_geojson(sheet_bounds: list[list[float]]) -> dict:
    """Build one MultiPolygon whose parts are the selected sheet rectangles."""

    polygons = []
    for bounds in sheet_bounds:
        if len(bounds) != 4:
            raise ValueError("invalid sheet bounds")
        min_lat, min_lon, max_lat, max_lon = (float(value) for value in bounds)
        if min_lat >= max_lat or min_lon >= max_lon:
            raise ValueError("invalid sheet bounds")
        polygons.append(
            [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]]
        )

    if not polygons:
        raise ValueError("no sheet bounds")
    return {
        "type": "FeatureCollection",
        "name": "selected_sheets_union",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "MultiPolygon", "coordinates": polygons},
        }],
    }


def validate_cog_source(source_path: str) -> dict:
    """Verify that GDAL can open the source and reports the COG layout."""

    result = subprocess.run(
        ["gdalinfo", "-json", source_path],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise InvalidCogSource("gdalinfo failed")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise InvalidCogSource("gdalinfo returned invalid JSON") from exc

    image_structure = info.get("metadata", {}).get("IMAGE_STRUCTURE", {})
    if (
        info.get("driverShortName") != "GTiff"
        or image_structure.get("LAYOUT") != "COG"
        or not info.get("bands")
        or not info.get("coordinateSystem")
    ):
        raise InvalidCogSource("source is not a georeferenced COG")
    return info


def _terminate_process(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            pass


def _run_gdal_command(
    command: list[str],
    *,
    progress_start: int,
    progress_end: int,
    on_progress: Callable[[int, str], None],
    is_cancelled: Callable[[], bool],
    stage: str,
    timeout_seconds: int = 6 * 60 * 60,
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_buffer = ""
    stderr_tail = b""
    started = time.monotonic()
    last_reported = progress_start
    on_progress(progress_start, stage)

    try:
        while process.poll() is None:
            if is_cancelled():
                _terminate_process(process)
                raise ClipExportCancelled()
            if time.monotonic() - started > timeout_seconds:
                _terminate_process(process)
                raise RuntimeError("GDAL command timed out")

            for key, _ in selector.select(timeout=0.5):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    continue
                if key.data == "stderr":
                    stderr_tail = (stderr_tail + chunk)[-16_384:]
                    continue
                stdout_buffer = (stdout_buffer + chunk.decode(errors="ignore"))[-1024:]
                matches = re.findall(r"(\d{1,3})(?=\.\.\.|\s+-\s+done)", stdout_buffer)
                if matches:
                    command_progress = min(100, int(matches[-1]))
                    mapped = progress_start + round(
                        (progress_end - progress_start) * command_progress / 100
                    )
                    if mapped >= last_reported + 2:
                        last_reported = mapped
                        on_progress(mapped, stage)
        for stream_name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            remainder = stream.read() or b""
            if stream_name == "stderr":
                stderr_tail = (stderr_tail + remainder)[-16_384:]
        if process.returncode != 0:
            raise RuntimeError(
                f"GDAL command failed with exit code {process.returncode}: "
                f"{stderr_tail.decode(errors='replace')}"
            )
        on_progress(progress_end, stage)
    finally:
        selector.close()


def run_union_clip_export(
    *,
    source_paths: list[str],
    sheet_bounds: list[list[float]],
    target_crs: str,
    target_gsd_cm: float | None,
    output_format: str,
    output_path: str,
    on_progress: Callable[[int, str], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """Mosaic all sources and clip them once with the selected union cutline."""

    if not source_paths:
        raise FileNotFoundError("no COG sources")
    if not re.fullmatch(r"EPSG:\d{4,5}", target_crs or ""):
        raise ValueError("invalid CRS")
    if target_gsd_cm is not None and not (0 < float(target_gsd_cm) <= 10_000):
        raise ValueError("invalid GSD")

    normalized_format = normalize_export_format(output_format)
    spec = FORMAT_SPECS[normalized_format]
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cutline_path = destination.parent / f".{destination.stem}.cutline.geojson"
    intermediate_path = destination.parent / f".{destination.stem}.working.tif"
    cutline_path.write_text(
        json.dumps(build_cutline_geojson(sheet_bounds), ensure_ascii=False),
        encoding="utf-8",
    )

    warp_command = [
        "gdalwarp",
        "-of", "GTiff",
        "-t_srs", target_crs,
        "-cutline", str(cutline_path),
        "-cutline_srs", "EPSG:4326",
        "-crop_to_cutline",
        "-dstnodata", "0",
        "-r", "bilinear",
        "-multi",
        "-wo", "NUM_THREADS=ALL_CPUS",
        "-overwrite",
        "-co", "TILED=YES",
        "-co", "COMPRESS=LZW",
        "-co", "BIGTIFF=IF_SAFER",
    ]
    if target_gsd_cm:
        target_resolution = float(target_gsd_cm) / 100.0
        if target_crs == "EPSG:4326":
            target_resolution /= 111_320.0
        warp_command += ["-tr", str(target_resolution), str(target_resolution)]
    warp_command += [*source_paths, str(intermediate_path)]

    try:
        _run_gdal_command(
            warp_command,
            progress_start=20,
            progress_end=85,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
            stage="선택 도엽 영역 클립 중",
        )
        if not intermediate_path.is_file() or intermediate_path.stat().st_size < 1024:
            raise RuntimeError("empty clip result")

        translate_command = [
            "gdal_translate",
            "-of", spec["driver"],
        ]
        if normalized_format in {"JPG", "PNG", "ECW"}:
            translate_command += ["-b", "1", "-b", "2", "-b", "3"]
        for option in spec["creation_options"]:
            translate_command += ["-co", option]
        translate_command += [str(intermediate_path), str(destination)]
        _run_gdal_command(
            translate_command,
            progress_start=86,
            progress_end=98,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
            stage="내보내기 파일 생성 중",
        )
        if not destination.is_file() or destination.stat().st_size < 1024:
            raise RuntimeError("empty export result")
        if normalized_format == "GeoTiff":
            validate_cog_source(str(destination))
    finally:
        for temporary in (cutline_path, intermediate_path):
            try:
                temporary.unlink()
            except OSError:
                pass


def cleanup_expired_clip_exports() -> None:
    root = Path(settings.EXPORT_ROOT_PATH) / "clip-jobs"
    if not root.is_dir():
        return
    cutoff = time.time() - max(1, int(settings.CLIP_EXPORT_RETENTION_DAYS)) * 86400
    for directory in root.iterdir():
        try:
            if directory.is_dir() and directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            continue
