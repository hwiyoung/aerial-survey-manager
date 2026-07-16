import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.upload_sessions import (
    MAX_MULTIPART_PARTS,
    MIN_MULTIPART_PART_SIZE,
    LocalUploadSession,
    UploadSessionError,
    expected_part_size,
    load_local_upload_session,
    multipart_part_count,
    save_local_upload_session,
    validate_completed_part_numbers,
    validate_upload_batch,
)


class UploadValidationTests(unittest.TestCase):
    def test_zero_part_size_is_rejected(self):
        with self.assertRaises(UploadSessionError):
            multipart_part_count(100, 0)

    def test_too_many_parts_are_rejected(self):
        with self.assertRaisesRegex(UploadSessionError, str(MAX_MULTIPART_PARTS)):
            multipart_part_count(
                MIN_MULTIPART_PART_SIZE * (MAX_MULTIPART_PARTS + 1),
                MIN_MULTIPART_PART_SIZE,
            )

    def test_duplicate_and_path_filenames_are_rejected(self):
        duplicate = [
            SimpleNamespace(filename="image.tif", size=10),
            SimpleNamespace(filename="image.tif", size=10),
        ]
        with self.assertRaisesRegex(UploadSessionError, "Duplicate filename"):
            validate_upload_batch(duplicate, MIN_MULTIPART_PART_SIZE, 100)

        traversal = [SimpleNamespace(filename="../image.tif", size=10)]
        with self.assertRaisesRegex(UploadSessionError, "Invalid filename"):
            validate_upload_batch(traversal, MIN_MULTIPART_PART_SIZE, 100)

    def test_expected_final_part_size(self):
        size = MIN_MULTIPART_PART_SIZE + 123
        self.assertEqual(
            expected_part_size(size, MIN_MULTIPART_PART_SIZE, 2),
            123,
        )

    def test_completed_parts_must_be_contiguous(self):
        with self.assertRaisesRegex(UploadSessionError, "contiguous"):
            validate_completed_part_numbers([1, 3])


class LocalUploadSessionTests(unittest.TestCase):
    def test_session_metadata_round_trip(self):
        session = LocalUploadSession(
            upload_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222",
            image_id="33333333-3333-3333-3333-333333333333",
            filename="image.tif",
            object_key=(
                "projects/22222222-2222-2222-2222-222222222222/"
                "source/images/image.tif"
            ),
            file_size=MIN_MULTIPART_PART_SIZE + 1,
            part_size=MIN_MULTIPART_PART_SIZE,
            part_count=2,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            staging_dir = Path(temp_dir) / "session"
            save_local_upload_session(staging_dir, session)
            self.assertEqual(load_local_upload_session(staging_dir), session)


if __name__ == "__main__":
    unittest.main()
