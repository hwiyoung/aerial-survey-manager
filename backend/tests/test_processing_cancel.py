import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.api.v1 import processing
from app.errors import AppError
from app.workers import tasks


class _FakeScalars:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return _FakeScalars(self.value)

    def scalar_one_or_none(self):
        return self.value


class _FakeDb:
    def __init__(self, job):
        self.job = job
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, _query):
        return _FakeResult(self.job)


def _job(project_id, status):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        status=status,
        progress=37,
        completed_at=None,
        error_message="old error",
        error_code="PROCESSING_STEP_FAILED",
        error_reference="ERR-20260722-AAAAAAAAAAAA",
        celery_task_id=f"task-{status}",
        crs_correction_status=None,
        crs_correction_source_crs=None,
        crs_correction_applied_at=None,
        crs_correction_error=None,
    )


@pytest.mark.parametrize(
    ("job_status", "active_task", "expected_terminate"),
    [
        ("queued", None, False),
        ("processing", {"task_id": "task-processing"}, True),
    ],
)
def test_cancel_endpoint_keeps_queue_and_runtime_state_consistent(
    job_status,
    active_task,
    expected_terminate,
):
    project_id = uuid4()
    job = _job(project_id, job_status)
    project = SimpleNamespace(id=project_id, status=job_status, progress=31)
    db = _FakeDb(job)
    call_order = []
    db.commit.side_effect = lambda: call_order.append("commit")
    current_user = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    active_payload = (
        {**active_task, "job_id": str(job.id)}
        if active_task
        else None
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        status_path = Path(temp_dir) / "status.json"
        with (
            patch.object(processing.PermissionChecker, "check", new=AsyncMock(return_value=True)),
            patch.object(processing, "_get_scoped_project", new=AsyncMock(return_value=project)),
            patch.object(processing, "_active_task_for_project", return_value=active_payload),
            patch.object(processing, "_remove_queued_celery_message", return_value=1) as remove_message,
            patch.object(processing, "clear_active_processing_task_cache") as clear_cache,
            patch.object(processing, "processing_status_path", return_value=status_path),
            patch.object(processing.manager, "broadcast", new=AsyncMock()) as broadcast,
            patch.object(
                tasks.celery_app.control,
                "revoke",
                new=Mock(side_effect=lambda *_args, **_kwargs: call_order.append("revoke")),
            ) as revoke,
        ):
            result = asyncio.run(
                processing.cancel_processing(project_id, current_user, db)
            )

        payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["status"] == "cancelled"
    assert result["job_id"] == str(job.id)
    assert job.status == "cancelled"
    assert job.progress == 37
    assert job.error_message is None
    assert job.error_code is None
    assert job.error_reference is None
    assert project.status == "cancelled"
    assert project.progress == 37
    assert payload["status"] == "cancelled"
    assert payload["job_id"] == str(job.id)
    assert payload["progress"] == 37
    revoke.assert_called_once_with(job.celery_task_id, terminate=expected_terminate)
    assert call_order == ["commit", "revoke"]
    remove_message.assert_called_once_with(job.celery_task_id, processing.PROCESSING_QUEUE)
    clear_cache.assert_called_once_with()
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    broadcast.assert_awaited_once()


def test_cancel_endpoint_keeps_cancelled_state_when_revoke_channel_fails():
    project_id = uuid4()
    job = _job(project_id, "processing")
    project = SimpleNamespace(id=project_id, status="processing", progress=31)
    db = _FakeDb(job)
    current_user = SimpleNamespace(id=uuid4(), organization_id=uuid4())

    with tempfile.TemporaryDirectory() as temp_dir:
        status_path = Path(temp_dir) / "status.json"
        with (
            patch.object(processing.PermissionChecker, "check", new=AsyncMock(return_value=True)),
            patch.object(processing, "_get_scoped_project", new=AsyncMock(return_value=project)),
            patch.object(
                processing,
                "_active_task_for_project",
                return_value={"task_id": job.celery_task_id, "job_id": str(job.id)},
            ),
            patch.object(processing, "_remove_queued_celery_message", return_value=0),
            patch.object(processing, "clear_active_processing_task_cache"),
            patch.object(processing, "processing_status_path", return_value=status_path),
            patch.object(processing.manager, "broadcast", new=AsyncMock()),
            patch.object(
                tasks.celery_app.control,
                "revoke",
                new=Mock(side_effect=RuntimeError("control channel unavailable")),
            ),
        ):
            result = asyncio.run(
                processing.cancel_processing(project_id, current_user, db)
            )

        payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["status"] == "cancelled"
    assert job.status == "cancelled"
    assert job.error_code is None
    assert project.status == "cancelled"
    assert payload["status"] == "cancelled"
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


def test_cancel_endpoint_reports_cancel_failure_when_state_cannot_be_persisted():
    project_id = uuid4()
    job = _job(project_id, "queued")
    project = SimpleNamespace(id=project_id, status="queued", progress=31)
    db = _FakeDb(job)
    db.commit.side_effect = RuntimeError("database unavailable")
    current_user = SimpleNamespace(id=uuid4(), organization_id=uuid4())

    with tempfile.TemporaryDirectory() as temp_dir:
        status_path = Path(temp_dir) / "status.json"
        with (
            patch.object(processing.PermissionChecker, "check", new=AsyncMock(return_value=True)),
            patch.object(processing, "_get_scoped_project", new=AsyncMock(return_value=project)),
            patch.object(processing, "_active_task_for_project", return_value=None),
            patch.object(processing, "processing_status_path", return_value=status_path),
            patch.object(tasks.celery_app.control, "revoke", new=Mock()) as revoke,
        ):
            with pytest.raises(AppError) as exc_info:
                asyncio.run(
                    processing.cancel_processing(project_id, current_user, db)
                )

        assert not status_path.exists()

    assert exc_info.value.code == "PROCESSING_CANCEL_FAILED"
    db.rollback.assert_awaited_once()
    revoke.assert_not_called()
