import unittest
from datetime import datetime
from uuid import UUID

from app.utils.storage_paths import orthomosaic_key


class OrthomosaicKeyTests(unittest.TestCase):
    def test_same_title_in_different_projects_has_different_key(self):
        first = UUID("11111111-1111-1111-1111-111111111111")
        second = UUID("22222222-2222-2222-2222-222222222222")

        first_key = orthomosaic_key(first, region="서울", title="2026 촬영")
        second_key = orthomosaic_key(second, region="서울", title="2026 촬영")

        self.assertNotEqual(first_key, second_key)
        self.assertEqual(
            first_key,
            "orthomosaic/11111111-1111-1111-1111-111111111111/서울_2026_촬영.tif",
        )

    def test_fallback_name_is_still_project_scoped(self):
        project_id = UUID("33333333-3333-3333-3333-333333333333")
        key = orthomosaic_key(
            project_id,
            target_crs="EPSG:5186",
            when=datetime(2026, 7, 16, 12, 30, 45),
        )

        self.assertEqual(
            key,
            "orthomosaic/33333333-3333-3333-3333-333333333333/"
            "orthomosaic_EPSG5186_20260716_123045.tif",
        )


if __name__ == "__main__":
    unittest.main()
