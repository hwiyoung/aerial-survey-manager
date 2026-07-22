"""Lazy, bounded previews for source images that are not projects yet."""

from __future__ import annotations

import base64
from functools import lru_cache
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.config import get_settings


settings = get_settings()


@lru_cache(maxsize=512)
def _preview_lock(cache_key: str) -> threading.Lock:
    """Serialize generation of the same preview inside the API process."""

    return threading.Lock()


def _tag_values(value: object) -> tuple[int, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(int(item) for item in value)
    return (int(value),)


def generate_thumbnail_sparse_tiff(
    source_path: str,
    dest_path: str,
    size: int = 640,
    sample_rows: int = 160,
) -> bool:
    """Quickly sample large, uncompressed RGB TIFFs without reading the full strip.

    Some aerial-camera TIFFs store the entire multi-gigabyte image as one
    uncompressed strip. Generic thumbnail readers load that whole strip even
    for a tiny preview. For the narrow, safe subset below, rows can be sampled
    directly from their byte offsets. Unsupported TIFF layouts return False so
    the regular GDAL/Pillow path remains the compatibility fallback.
    """

    source = Path(source_path)
    if source.suffix.lower() not in {".tif", ".tiff"}:
        return False

    from PIL import Image as PILImage

    PILImage.MAX_IMAGE_PIXELS = max(PILImage.MAX_IMAGE_PIXELS or 0, 600_000_000)
    with PILImage.open(source) as image:
        tags = image.tag_v2
        width, height = image.size
        bits_per_sample = _tag_values(tags.get(258, (8, 8, 8)))
        compression = int(tags.get(259, 1))
        photometric = int(tags.get(262, 2))
        samples_per_pixel = int(tags.get(277, 3))
        rows_per_strip = int(tags.get(278, height))
        strip_offsets = _tag_values(tags.get(273, ()))
        strip_byte_counts = _tag_values(tags.get(279, ()))
        planar_configuration = int(tags.get(284, 1))
        orientation = int(tags.get(274, 1))

    supported = (
        width > 0
        and height > 0
        and size > 0
        and compression == 1
        and photometric == 2
        and samples_per_pixel in {3, 4}
        and len(bits_per_sample) >= samples_per_pixel
        and all(value == 8 for value in bits_per_sample[:samples_per_pixel])
        and rows_per_strip > 0
        and len(strip_offsets) == len(strip_byte_counts)
        and len(strip_offsets) > 0
        and planar_configuration == 1
        and orientation == 1
    )
    if not supported:
        return False

    scale = min(1.0, size / max(width, height))
    output_width = max(1, round(width * scale))
    output_height = max(1, round(height * scale))
    sampled_height = min(output_height, max(1, sample_rows))
    source_x_offsets = [
        min(width - 1, int((column + 0.5) * width / output_width)) * samples_per_pixel
        for column in range(output_width)
    ]
    source_rows = [
        min(height - 1, int((row + 0.5) * height / sampled_height))
        for row in range(sampled_height)
    ]
    source_row_bytes = width * samples_per_pixel
    output = bytearray(output_width * sampled_height * 3)

    descriptor = os.open(source, os.O_RDONLY)
    try:
        for output_y, source_y in enumerate(source_rows):
            strip_index = source_y // rows_per_strip
            if strip_index >= len(strip_offsets):
                return False
            row_in_strip = source_y % rows_per_strip
            relative_offset = row_in_strip * source_row_bytes
            if relative_offset + source_row_bytes > strip_byte_counts[strip_index]:
                return False
            source_row = os.pread(
                descriptor,
                source_row_bytes,
                strip_offsets[strip_index] + relative_offset,
            )
            if len(source_row) != source_row_bytes:
                return False

            output_row_offset = output_y * output_width * 3
            for output_x, source_x_offset in enumerate(source_x_offsets):
                output_offset = output_row_offset + output_x * 3
                output[output_offset:output_offset + 3] = source_row[source_x_offset:source_x_offset + 3]
    finally:
        os.close(descriptor)

    preview = PILImage.frombytes("RGB", (output_width, sampled_height), bytes(output))
    if sampled_height != output_height:
        preview = preview.resize((output_width, output_height), PILImage.Resampling.BILINEAR)
    preview.save(dest_path, "JPEG", quality=85)
    return True


def generate_thumbnail_gdal(source_path: str, dest_path: str, size: int = 320) -> None:
    """Create a small JPEG using GDAL and source overviews when available."""

    info = subprocess.run(
        ["gdalinfo", "-json", source_path],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if info.returncode != 0:
        raise RuntimeError("gdalinfo failed")

    meta = json.loads(info.stdout)
    bands = meta.get("bands", [])
    band_count = len(bands)
    data_type = bands[0].get("type", "Byte") if bands else "Byte"
    command = [
        "gdal_translate",
        "-of",
        "JPEG",
        "-outsize",
        str(size),
        "0",
        "-r",
        "average",
    ]
    if band_count > 3:
        command += ["-b", "1", "-b", "2", "-b", "3"]
    if data_type != "Byte":
        command += ["-scale"]
    command += [source_path, dest_path]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("gdal_translate failed")


def generate_thumbnail_pil(source_path: str, dest_path: str, size: int = 320) -> None:
    """Create a small JPEG with Pillow as a GDAL fallback."""

    from PIL import Image as PILImage

    PILImage.MAX_IMAGE_PIXELS = 300_000_000
    with PILImage.open(source_path) as image:
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((size, size))
        image.save(dest_path, "JPEG", quality=85)


def _preview_cache_key(source: Path, size: int) -> str:
    stat = source.stat()
    fingerprint = (
        f"{source.resolve()}\0{stat.st_dev}\0{stat.st_ino}\0"
        f"{stat.st_size}\0{stat.st_mtime_ns}\0{size}"
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _cleanup_preview_cache(cache_root: Path) -> None:
    now = time.time()
    max_age = max(0, int(settings.IMAGE_PREVIEW_CACHE_RETENTION_DAYS)) * 86400
    max_bytes = max(0, int(settings.IMAGE_PREVIEW_CACHE_MAX_BYTES))
    files: list[tuple[Path, os.stat_result]] = []

    for path in cache_root.glob("*.jpg"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if max_age and now - stat.st_mtime > max_age:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        files.append((path, stat))

    total = sum(stat.st_size for _, stat in files)
    if not max_bytes or total <= max_bytes:
        return
    for path, stat in sorted(files, key=lambda item: item[1].st_mtime):
        try:
            path.unlink()
            total -= stat.st_size
        except OSError:
            pass
        if total <= max_bytes:
            break


def get_image_preview(source_path: str, size: int = 640) -> dict[str, object]:
    """Return a cached data URL, generating it atomically on first request."""

    source = Path(source_path).resolve()
    cache_root = Path(settings.IMAGE_PREVIEW_CACHE_PATH)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_key = _preview_cache_key(source, size)
    cache_path = cache_root / f"{cache_key}.jpg"

    with _preview_lock(cache_key):
        cache_hit = cache_path.is_file() and cache_path.stat().st_size > 0
        if not cache_hit:
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="preview-",
                    suffix=".jpg",
                    dir=cache_root,
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                generated = False
                try:
                    generated = generate_thumbnail_sparse_tiff(str(source), str(temporary_path), size)
                except Exception:
                    generated = False
                if not generated:
                    try:
                        generate_thumbnail_gdal(str(source), str(temporary_path), size)
                    except Exception:
                        generate_thumbnail_pil(str(source), str(temporary_path), size)
                os.replace(temporary_path, cache_path)
                temporary_path = None
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink()
                    except OSError:
                        pass

    _cleanup_preview_cache(cache_root)
    encoded = base64.b64encode(cache_path.read_bytes()).decode("ascii")
    return {
        "data_url": f"data:image/jpeg;base64,{encoded}",
        "width": size,
        "cache_hit": cache_hit,
    }
