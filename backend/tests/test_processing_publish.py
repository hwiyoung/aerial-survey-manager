import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from app.workers.tasks import (
    _select_orthomosaic_target,
    _validate_and_publish_cog,
)


class _RecordingStorage:
    def __init__(self, events):
        self.events = events

    def upload_file(self, local_path, object_name, content_type=None):
        self.events.append(("publish", object_name, content_type))
        return object_name


class ProcessingPublishTests(unittest.TestCase):
    def test_cog_is_inspected_before_it_is_published(self):
        events = []
        storage = _RecordingStorage(events)

        with tempfile.TemporaryDirectory() as temp_dir:
            cog_path = Path(temp_dir) / "result.tif"
            cog_path.write_bytes(b"validated-cog")

            with (
                patch(
                    "app.workers.tasks.calculate_file_checksum",
                    side_effect=lambda path: events.append(("checksum", path)) or "abc123",
                ),
                patch(
                    "app.workers.tasks.get_orthophoto_bounds",
                    side_effect=lambda path: events.append(("bounds", path)) or "SRID=4326;POLYGON EMPTY",
                ),
            ):
                checksum, file_size, bounds = _validate_and_publish_cog(
                    cog_path,
                    "orthomosaic/project/job.tif",
                    storage,
                )

        self.assertEqual([event[0] for event in events], ["checksum", "bounds", "publish"])
        self.assertEqual(checksum, "abc123")
        self.assertEqual(file_size, len(b"validated-cog"))
        self.assertEqual(bounds, "SRID=4326;POLYGON EMPTY")

    def test_same_project_can_atomically_replace_its_flat_output(self):
        key = "orthomosaic/서울_테스트.tif"
        project = SimpleNamespace(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            ortho_path=key,
        )
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = []
        storage = Mock()
        storage.object_exists.return_value = True

        selected = _select_orthomosaic_target(db, project, key, storage)

        self.assertEqual(selected, key)

    def test_other_project_gets_next_numbered_flat_output(self):
        key = "orthomosaic/서울_테스트.tif"
        project = SimpleNamespace(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            ortho_path=None,
        )
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = [(key,)]
        storage = Mock()
        storage.object_exists.return_value = False

        selected = _select_orthomosaic_target(db, project, key, storage)

        self.assertEqual(selected, "orthomosaic/서울_테스트 (1).tif")

    def test_untracked_existing_outputs_are_skipped_in_number_order(self):
        key = "orthomosaic/서울_테스트.tif"
        project = SimpleNamespace(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            ortho_path=None,
        )
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = []
        storage = Mock()
        storage.object_exists.side_effect = lambda candidate: candidate in {
            key,
            "orthomosaic/서울_테스트 (1).tif",
        }

        selected = _select_orthomosaic_target(db, project, key, storage)

        self.assertEqual(selected, "orthomosaic/서울_테스트 (2).tif")

    def test_same_project_keeps_its_numbered_name_when_reprocessed(self):
        key = "orthomosaic/서울_테스트.tif"
        current = "orthomosaic/서울_테스트 (2).tif"
        project = SimpleNamespace(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            ortho_path=current,
        )
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = []
        storage = Mock()
        storage.object_exists.return_value = True

        selected = _select_orthomosaic_target(db, project, key, storage)

        self.assertEqual(selected, current)


if __name__ == "__main__":
    unittest.main()
