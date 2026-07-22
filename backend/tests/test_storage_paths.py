import unittest
from datetime import datetime
from uuid import UUID

from app.utils.storage_paths import (
    is_numbered_orthomosaic_variant,
    numbered_orthomosaic_key,
    orthomosaic_key,
)


class OrthomosaicKeyTests(unittest.TestCase):
    def test_title_uses_flat_shared_layout(self):
        first = UUID("11111111-1111-1111-1111-111111111111")
        second = UUID("22222222-2222-2222-2222-222222222222")

        first_key = orthomosaic_key(first, region="서울", title="2026 촬영")
        second_key = orthomosaic_key(second, region="서울", title="2026 촬영")

        self.assertEqual(first_key, second_key)
        self.assertEqual(
            first_key,
            "orthomosaic/서울_2026_촬영.tif",
        )

    def test_fallback_uuid_is_in_filename_not_directory(self):
        project_id = UUID("33333333-3333-3333-3333-333333333333")
        key = orthomosaic_key(
            project_id,
            target_crs="EPSG:5186",
            when=datetime(2026, 7, 16, 12, 30, 45),
        )

        self.assertEqual(
            key,
            "orthomosaic/33333333-3333-3333-3333-333333333333_"
            "orthomosaic_EPSG5186_20260716_123045.tif",
        )

    def test_project_id_never_creates_a_subdirectory(self):
        key = orthomosaic_key(
            UUID("44444444-4444-4444-4444-444444444444"),
            region="경기",
            title="테스트 프로젝트",
        )

        self.assertEqual(len(key.split("/")), 2)

    def test_duplicate_names_use_pc_style_numbering(self):
        key = "orthomosaic/서울_테스트.tif"

        self.assertEqual(numbered_orthomosaic_key(key, 0), key)
        self.assertEqual(
            numbered_orthomosaic_key(key, 1),
            "orthomosaic/서울_테스트 (1).tif",
        )
        self.assertEqual(
            numbered_orthomosaic_key(key, 2),
            "orthomosaic/서울_테스트 (2).tif",
        )

    def test_numbered_variant_recognizes_only_same_base_name(self):
        key = "orthomosaic/서울_테스트.tif"

        self.assertTrue(is_numbered_orthomosaic_variant(key, key))
        self.assertTrue(
            is_numbered_orthomosaic_variant(
                "orthomosaic/서울_테스트 (12).tif",
                key,
            )
        )
        self.assertFalse(
            is_numbered_orthomosaic_variant(
                "orthomosaic/서울_다른_프로젝트 (1).tif",
                key,
            )
        )


if __name__ == "__main__":
    unittest.main()
