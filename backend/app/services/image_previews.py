"""Lazy, bounded previews for source images that are not projects yet."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import get_settings


settings = get_settings()


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
    cache_path = cache_root / f"{_preview_cache_key(source, size)}.jpg"
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
