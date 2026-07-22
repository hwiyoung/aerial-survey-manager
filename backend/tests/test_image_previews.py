import asyncio
from pathlib import Path

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
