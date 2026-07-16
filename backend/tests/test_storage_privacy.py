import tempfile
import unittest
from unittest.mock import Mock, patch

from app.services.storage_local import LocalStorageBackend
from app.services.storage_minio import MinIOStorageBackend
from app.services import storage_minio
from app.utils.storage_paths import (
    is_private_project_key,
    is_public_project_artifact_key,
    is_source_image_key,
)


class StoragePrivacyTests(unittest.TestCase):
    def test_only_original_source_images_are_private(self):
        original = (
            "projects/11111111-1111-1111-1111-111111111111/"
            "source/images/image.tif"
        )
        thumbnail = (
            "projects/11111111-1111-1111-1111-111111111111/"
            "source/thumbnails/image.tif.jpg"
        )
        self.assertTrue(is_source_image_key(original))
        self.assertFalse(is_source_image_key(thumbnail))
        self.assertTrue(is_private_project_key(original))
        self.assertTrue(is_public_project_artifact_key(thumbnail))
        self.assertFalse(is_private_project_key(thumbnail))

    def test_local_original_url_uses_authenticated_endpoint(self):
        original = (
            "projects/11111111-1111-1111-1111-111111111111/"
            "source/images/image.tif"
        )
        thumbnail = (
            "projects/11111111-1111-1111-1111-111111111111/"
            "source/thumbnails/image.tif.jpg"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = LocalStorageBackend(temp_dir)
            self.assertEqual(
                storage.get_presigned_url(original),
                f"/api/v1/storage/files/{original}",
            )
            self.assertEqual(
                storage.get_presigned_url(thumbnail),
                f"/storage/{thumbnail}",
            )

    def test_minio_project_url_is_signed_and_routed_through_nginx(self):
        original = (
            "projects/11111111-1111-1111-1111-111111111111/"
            "source/images/image.tif"
        )
        backend = MinIOStorageBackend.__new__(MinIOStorageBackend)
        backend.bucket = "aerial-survey"
        backend.client = Mock()
        backend.client.presigned_get_object.return_value = (
            "http://minio:9000/aerial-survey/"
            f"{original}?X-Amz-Signature=signed"
        )

        with (
            patch.object(storage_minio.settings, "MINIO_PUBLIC_ENDPOINT", "192.168.10.203:18100"),
            patch.object(storage_minio.settings, "MINIO_ENDPOINT", "minio:9000"),
            patch.object(storage_minio.settings, "MINIO_SECURE", False),
        ):
            url = backend.get_presigned_url(original)

        self.assertEqual(
            url,
            "http://192.168.10.203:18100/storage/aerial-survey/"
            f"{original}?X-Amz-Signature=signed",
        )


if __name__ == "__main__":
    unittest.main()
