import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.v1 import processing


class ProcessingEnginePolicyTests(unittest.TestCase):
    def test_catalog_exposes_only_metashape(self):
        with patch.object(
            processing,
            "get_settings",
            return_value=SimpleNamespace(ENABLE_METASHAPE_ENGINE=True),
        ):
            policies = processing._get_processing_engine_policies()

        self.assertEqual(list(policies), ["metashape"])
        self.assertTrue(policies["metashape"]["enabled"])
        self.assertEqual(
            policies["metashape"]["queue_name"],
            processing.PROCESSING_QUEUE,
        )

    def test_disabled_metashape_has_no_supported_default(self):
        with patch.object(
            processing,
            "get_settings",
            return_value=SimpleNamespace(ENABLE_METASHAPE_ENGINE=False),
        ):
            self.assertEqual(processing._get_supported_processing_engines(), set())
            self.assertIsNone(processing._get_default_processing_engine())


if __name__ == "__main__":
    unittest.main()
