import tempfile
import unittest
from pathlib import Path

from app.services.storage_local import LocalStorageBackend


class LocalStorageMoveTests(unittest.TestCase):
    def test_move_file_atomically_replaces_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = LocalStorageBackend(str(root / "storage"))
            object_name = "orthomosaic/서울_테스트.tif"
            destination = Path(storage.get_local_path(object_name))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"old-complete-cog")
            source = root / "new-complete-cog.tif"
            source.write_bytes(b"new-complete-cog")

            storage.move_file(str(source), object_name)

            self.assertEqual(destination.read_bytes(), b"new-complete-cog")
            self.assertFalse(source.exists())
            self.assertEqual(list(destination.parent.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
