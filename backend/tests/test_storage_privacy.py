import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from app.api.v1.storage_files import _project_ids_for_storage_key
from app.services.storage_local import LocalStorageBackend
from app.services.storage_minio import MinIOStorageBackend
from app.services.s3_multipart import S3MultipartService
from app.services import storage_minio
from app.utils.storage_paths import (
    is_private_project_key,
    is_source_image_key,
)


class StoragePrivacyTests(unittest.TestCase):
    def test_all_project_artifacts_are_private(self):
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
        self.assertTrue(is_private_project_key(thumbnail))
        self.assertTrue(
            is_private_project_key(
                "orthomosaic/11111111-1111-1111-1111-111111111111/result.tif"
            )
        )

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
                f"/api/v1/storage/files/{thumbnail}",
            )

    def test_minio_project_url_is_signed_and_same_origin(self):
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

        with patch.object(storage_minio.settings, "MINIO_SECURE", False):
            url = backend.get_presigned_url(original)

        self.assertEqual(
            url,
            "/storage/aerial-survey/"
            f"{original}?X-Amz-Signature=signed",
        )

    def test_multipart_upload_url_is_same_origin(self):
        service = S3MultipartService.__new__(S3MultipartService)
        url = service._transform_url_for_nginx_proxy(
            "http://minio:9000/aerial-survey/projects/example"
            "?X-Amz-Signature=signed"
        )
        self.assertEqual(
            url,
            "/storage/aerial-survey/projects/example?X-Amz-Signature=signed",
        )


class FlatOrthomosaicOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_flat_orthomosaic_owner_is_resolved_from_project_path(self):
        project_id = UUID("11111111-1111-1111-1111-111111111111")
        scalar_result = Mock()
        scalar_result.all.return_value = [project_id]
        result = Mock()
        result.scalars.return_value = scalar_result
        db = AsyncMock()
        db.execute.return_value = result

        owners = await _project_ids_for_storage_key(
            "orthomosaic/서울_테스트.tif",
            db,
        )

        self.assertEqual(owners, [project_id])
        db.execute.assert_awaited_once()

    async def test_nested_project_key_uses_encoded_uuid_without_query(self):
        project_id = UUID("22222222-2222-2222-2222-222222222222")
        db = AsyncMock()

        owners = await _project_ids_for_storage_key(
            f"projects/{project_id}/source/images/a.jpg",
            db,
        )

        self.assertEqual(owners, [project_id])
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
