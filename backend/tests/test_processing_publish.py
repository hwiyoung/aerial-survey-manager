import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.workers.tasks import _validate_and_publish_cog


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


if __name__ == "__main__":
    unittest.main()
