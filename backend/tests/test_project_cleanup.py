import tempfile
import unittest
from unittest.mock import patch

from app.services.project_cleanup import cleanup_project_storage
from app.services.storage_local import LocalStorageBackend


class ProjectCleanupTests(unittest.TestCase):
    def test_project_prefixes_are_deleted_and_external_sources_are_preserved(self):
        project_id = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = LocalStorageBackend(temp_dir)
            source_key = f"projects/{project_id}/source/images/image.jpg"
            storage.upload_bytes(b"source", source_key)
            storage.upload_bytes(
                b"thumb",
                f"projects/{project_id}/source/thumbnails/image.jpg",
            )
            storage.upload_bytes(
                b"ortho",
                f"orthomosaic/{project_id}/result.tif",
            )

            with patch(
                "app.services.project_cleanup.get_storage",
                return_value=storage,
            ):
                cleanup_project_storage(
                    project_id,
                    [source_key, "/media/external/image.jpg"],
                    f"orthomosaic/{project_id}/result.tif",
                )

            self.assertEqual(storage.list_objects(f"projects/{project_id}/"), [])
            self.assertEqual(storage.list_objects(f"orthomosaic/{project_id}/"), [])


if __name__ == "__main__":
    unittest.main()
