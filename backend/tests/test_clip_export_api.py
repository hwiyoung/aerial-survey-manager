import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from app.api.v1 import download


class ClipExportApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_result_removes_file_reference_but_keeps_history(self):
        job = SimpleNamespace(
            id=UUID("33333333-3333-3333-3333-333333333333"),
            project_ids=["11111111-1111-1111-1111-111111111111"],
            sheet_ids=["37806043"],
            scale=5000,
            output_format="GeoTiff",
            output_crs="EPSG:5186",
            output_gsd=5.0,
            base_filename="수도권남부_테스트_ortho",
            output_filename="수도권남부_테스트_ortho_clip.tif",
            status="completed",
            progress=100,
            stage="완료",
            error_code=None,
            error_reference=None,
            result_path="/data/exports/수도권남부_테스트_ortho_clip.tif",
            result_size=1234,
            created_at=None,
            started_at=None,
            completed_at=None,
        )
        db = SimpleNamespace(commit=AsyncMock())

        with (
            patch.object(
                download,
                "_get_user_clip_job",
                new=AsyncMock(return_value=job),
            ),
            patch.object(
                download,
                "delete_managed_clip_result",
                new=Mock(return_value=True),
            ) as delete_result,
            patch(
                "app.config.get_settings",
                return_value=SimpleNamespace(EXPORT_ROOT_PATH="/data/exports"),
            ),
        ):
            response = await download.delete_clip_export_result(
                job.id,
                SimpleNamespace(id=UUID("22222222-2222-2222-2222-222222222222")),
                db,
            )

        delete_result.assert_called_once_with(
            "/data/exports/수도권남부_테스트_ortho_clip.tif",
            "/data/exports",
            expected_filename="수도권남부_테스트_ortho_clip.tif",
        )
        db.commit.assert_awaited_once()
        self.assertEqual(job.stage, "결과 삭제됨")
        self.assertIsNone(job.result_path)
        self.assertIsNone(job.result_size)
        self.assertEqual(response["filename"], "수도권남부_테스트_ortho_clip.tif")
        self.assertFalse(response["download_available"])


if __name__ == "__main__":
    unittest.main()
