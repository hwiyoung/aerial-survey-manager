import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest
from PIL import Image

from app.api.v1 import filesystem
from app.errors import AppError
from app.services import image_previews


def _configure_preview_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache"
    monkeypatch.setattr(image_previews.settings, "IMAGE_PREVIEW_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(image_previews.settings, "IMAGE_PREVIEW_CACHE_RETENTION_DAYS", 7)
    monkeypatch.setattr(image_previews.settings, "IMAGE_PREVIEW_CACHE_MAX_BYTES", 1024 * 1024)
    return cache_path


def test_preview_is_generated_lazily_and_reused(monkeypatch, tmp_path):
    cache_path = _configure_preview_cache(monkeypatch, tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (640, 320), color=(10, 20, 30)).save(source)
    monkeypatch.setattr(
        image_previews,
        "generate_thumbnail_gdal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no gdal")),
    )

    first = image_previews.get_image_preview(str(source), size=128)
    second = image_previews.get_image_preview(str(source), size=128)

    assert first["data_url"].startswith("data:image/jpeg;base64,")
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert len(list(cache_path.glob("*.jpg"))) == 1


def test_preview_cache_key_changes_when_source_changes(monkeypatch, tmp_path):
    cache_path = _configure_preview_cache(monkeypatch, tmp_path)
    source = tmp_path / "source.jpg"
    Image.new("RGB", (32, 32), color="red").save(source)
    monkeypatch.setattr(
        image_previews,
        "generate_thumbnail_gdal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no gdal")),
    )

    image_previews.get_image_preview(str(source), size=32)
    Image.new("RGB", (48, 48), color="blue").save(source)
    image_previews.get_image_preview(str(source), size=32)

    assert len(list(cache_path.glob("*.jpg"))) == 2


def test_uncompressed_rgb_tiff_uses_sparse_preview_path(monkeypatch, tmp_path):
    _configure_preview_cache(monkeypatch, tmp_path)
    source = tmp_path / "source.tif"
    Image.new("RGB", (120, 300), color=(30, 90, 150)).save(source, compression="raw")
    monkeypatch.setattr(
        image_previews,
        "generate_thumbnail_gdal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("GDAL fallback should not run")),
    )

    result = image_previews.get_image_preview(str(source), size=128)

    assert result["data_url"].startswith("data:image/jpeg;base64,")
    assert result["cache_hit"] is False


def test_concurrent_requests_generate_same_preview_once(monkeypatch, tmp_path):
    _configure_preview_cache(monkeypatch, tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 64), color=(50, 100, 150)).save(source)
    calls = 0

    def generate(_source, destination, _size):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        Image.new("RGB", (32, 32), color=(50, 100, 150)).save(destination, "JPEG")

    monkeypatch.setattr(image_previews, "generate_thumbnail_gdal", generate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: image_previews.get_image_preview(str(source), size=32), range(2)))

    assert calls == 1
    assert sorted(result["cache_hit"] for result in results) == [False, True]


def test_preview_endpoint_rejects_paths_outside_allowlist(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside.jpg"
    allowed.mkdir()
    outside.write_bytes(b"not-read")
    monkeypatch.setenv("FILESYSTEM_ALLOWED_ROOTS", str(allowed))

    with pytest.raises(AppError) as exc_info:
        asyncio.run(
            filesystem.create_image_preview(
                filesystem.ImagePreviewRequest(path=str(outside)),
                current_user=object(),
            )
        )

    assert exc_info.value.code == "AUTH_ACCESS_DENIED"
