import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api.v1 import camera_models
from app.errors import AppError
from app.services import camera_io


SAMPLE_IO = """설명,값
$CAMERA
,$CAMERA_NAME:,카메라A
,$LENS_SN:,업체A
,$FOCAL_LENGTH:,100.5
,$PRINCIPAL_POINT_AUTOCOLLIMATION:,0.1,-0.2
,$SENSOR_SIZE:,10000,12000
,$PIXEL_SIZE:,5.2,5.2
,$UNKNOWN_FIELD:,preserve-me
$END_CAMERA
"""


def _configure_paths(monkeypatch, tmp_path):
    source_path = tmp_path / "package" / "io.csv"
    config_path = tmp_path / "config" / "io.csv"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(SAMPLE_IO.encode("cp949"))
    monkeypatch.setattr(camera_io.settings, "CAMERA_IO_SOURCE_PATH", str(source_path))
    monkeypatch.setattr(camera_io.settings, "CAMERA_IO_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(camera_io.settings, "CAMERA_IO_BACKUP_COUNT", 2)
    return source_path, config_path


def test_cp949_io_is_parsed_and_unknown_fields_remain_in_document(monkeypatch, tmp_path):
    _, config_path = _configure_paths(monkeypatch, tmp_path)

    document = camera_io.read_io_document()

    assert document["encoding"] == "cp949"
    assert document["camera_block_count"] == 1
    assert document["model_count"] == 1
    assert "$UNKNOWN_FIELD:,preserve-me" in document["content"]
    assert config_path.read_bytes() == SAMPLE_IO.encode("cp949")


def test_io_update_creates_backup_and_can_restore_previous_bytes(monkeypatch, tmp_path):
    _, config_path = _configure_paths(monkeypatch, tmp_path)
    original = camera_io.read_io_document()
    updated_content = original["content"].replace("카메라A", "카메라B")

    prepared = camera_io.prepare_io_update(updated_content, original["sha256"])
    backup_path = camera_io.backup_and_replace_io(prepared)

    assert backup_path.read_bytes() == SAMPLE_IO.encode("cp949")
    assert "카메라B" in camera_io.decode_io_bytes(config_path.read_bytes())[0]
    camera_io.restore_io(prepared)
    assert config_path.read_bytes() == SAMPLE_IO.encode("cp949")


def test_io_update_rejects_stale_checksum_and_invalid_required_values(
    monkeypatch,
    tmp_path,
):
    _configure_paths(monkeypatch, tmp_path)
    document = camera_io.read_io_document()

    with pytest.raises(FileExistsError):
        camera_io.prepare_io_update(document["content"], "0" * 64)
    with pytest.raises(ValueError, match="invalid focal_length"):
        camera_io.prepare_io_update(
            document["content"].replace("$FOCAL_LENGTH:,100.5", "$FOCAL_LENGTH:,0"),
            document["sha256"],
        )


class _FakeDb:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


def test_io_api_restores_file_when_db_sync_fails():
    request = camera_models.CameraIoUpdateRequest(
        content=SAMPLE_IO,
        expected_sha256="0" * 64,
    )
    prepared = {"entries": [{"name": "Camera"}]}
    db = _FakeDb()

    with (
        patch.object(camera_models, "prepare_io_update", return_value=prepared),
        patch.object(camera_models, "backup_and_replace_io", return_value=Path("backup.csv")),
        patch.object(
            camera_models,
            "sync_standard_camera_models",
            new=AsyncMock(side_effect=RuntimeError("db failed")),
        ),
        patch.object(camera_models, "restore_io") as restore,
    ):
        with pytest.raises(AppError) as exc_info:
            asyncio.run(
                camera_models.update_camera_io_config(
                    request,
                    SimpleNamespace(),
                    db,
                )
            )

    assert exc_info.value.code == "CAMERA_IO_SYNC_FAILED"
    db.rollback.assert_awaited_once()
    restore.assert_called_once_with(prepared)


def test_io_api_commits_sync_and_returns_new_document():
    request = camera_models.CameraIoUpdateRequest(
        content=SAMPLE_IO,
        expected_sha256="0" * 64,
    )
    prepared = {"entries": [{"name": "Camera"}]}
    db = _FakeDb()
    sync_result = {"inserted": 1, "updated": 0}
    document = {
        "content": SAMPLE_IO,
        "sha256": "1" * 64,
        "encoding": "cp949",
        "camera_block_count": 1,
        "model_count": 1,
        "backup_count": 1,
    }

    with (
        patch.object(camera_models, "prepare_io_update", return_value=prepared),
        patch.object(camera_models, "backup_and_replace_io", return_value=Path("backup.csv")),
        patch.object(
            camera_models,
            "sync_standard_camera_models",
            new=AsyncMock(return_value=sync_result),
        ),
        patch.object(camera_models, "cleanup_io_backups", new=Mock(return_value=0)),
        patch.object(camera_models, "read_io_document", return_value=document),
    ):
        result = asyncio.run(
            camera_models.update_camera_io_config(
                request,
                SimpleNamespace(),
                db,
            )
        )

    db.commit.assert_awaited_once()
    assert result["backup_created"] == "backup.csv"
    assert result["sync"] == sync_result
