import json
import os
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import processing_logs


def _configure(monkeypatch, temp_path: Path, **overrides):
    defaults = {
        "PROCESSING_DATA_PATH": str(temp_path),
        "PROCESSING_LOG_MAX_BYTES": 10,
        "PROCESSING_LOG_BACKUP_COUNT": 2,
        "PROCESSING_ERROR_BUNDLE_RETENTION_DAYS": 30,
        "PROCESSING_ERROR_BUNDLE_PROJECT_LIMIT": 20,
        "PROCESSING_ERROR_BUNDLE_TOTAL_MAX_BYTES": 1024 * 1024,
        "PROCESSING_ERROR_BUNDLE_LOG_TAIL_BYTES": 64,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(processing_logs.settings, name, value)


def test_processing_log_rotates_and_tail_reads_newest_backup(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    log_path = tmp_path / "processing.log"

    processing_logs.append_processing_log(log_path, "first-line\n")
    assert not log_path.exists()
    assert log_path.with_name("processing.log.1").read_text() == "first-line\n"

    processing_logs.append_processing_log(log_path, "second-line\n")
    processing_logs.append_processing_log(log_path, "third-line\n")

    assert log_path.with_name("processing.log.1").read_text() == "third-line\n"
    assert log_path.with_name("processing.log.2").read_text() == "second-line\n"
    assert processing_logs.read_processing_log_tail(log_path) == (
        "second-line\nthird-line\n"
    )

    log_path.write_text("current-line\n", encoding="utf-8")
    assert processing_logs.read_processing_log_tail(log_path, lines=2) == (
        "third-line\ncurrent-line\n"
    )


def test_error_bundle_contains_reference_logs_and_state(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    project_id = "project-1"
    log_path = processing_logs.processing_log_path(project_id)
    log_path.parent.mkdir(parents=True)
    log_path.write_text("raw internal processing output\n", encoding="utf-8")
    status_path = processing_logs.processing_status_path(project_id)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text('{"status":"error"}\n', encoding="utf-8")

    bundle_path = processing_logs.create_processing_error_bundle(
        project_id,
        "ERR-20260722-ABC123",
        error_code="PROCESSING_STEP_FAILED",
        job_id="job-1",
        technical_error="internal detail",
    )

    assert bundle_path is not None
    with tarfile.open(bundle_path, "r:gz") as archive:
        names = set(archive.getnames())
        metadata = json.load(archive.extractfile("metadata.json"))
        log_payload = archive.extractfile("logs/processing.log").read().decode()
    assert "state/status.json" in names
    assert metadata["error_reference"] == "ERR-20260722-ABC123"
    assert metadata["error_code"] == "PROCESSING_STEP_FAILED"
    assert "raw internal processing output" in log_payload


def test_error_bundle_cleanup_enforces_age_project_count_and_total_size(
    monkeypatch,
    tmp_path,
):
    _configure(
        monkeypatch,
        tmp_path,
        PROCESSING_ERROR_BUNDLE_RETENTION_DAYS=2,
        PROCESSING_ERROR_BUNDLE_PROJECT_LIMIT=2,
        PROCESSING_ERROR_BUNDLE_TOTAL_MAX_BYTES=7,
    )
    now = datetime(2026, 7, 22, tzinfo=timezone.utc)

    def create(project_id: str, name: str, payload: bytes, age_hours: int) -> Path:
        directory = processing_logs.processing_error_bundles_dir(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(payload)
        modified = (now - timedelta(hours=age_hours)).timestamp()
        os.utime(path, (modified, modified))
        return path

    expired = create("project-a", "expired.tar.gz", b"old", 72)
    oldest = create("project-a", "oldest.tar.gz", b"111", 3)
    middle = create("project-a", "middle.tar.gz", b"222", 2)
    newest = create("project-a", "newest.tar.gz", b"333", 1)
    other = create("project-b", "other.tar.gz", b"444", 0)

    result = processing_logs.cleanup_processing_error_bundles(now=now)

    assert result["removed_files"] == 3
    assert not expired.exists()
    assert not oldest.exists()
    assert not middle.exists()
    assert newest.exists()
    assert other.exists()
    assert result["remaining_files"] == 2
