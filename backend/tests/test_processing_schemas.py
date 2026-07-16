import unittest

from app.schemas.preset import PresetOptionsSchema


class ProcessingSchemaTests(unittest.TestCase):
    def test_preset_preserves_point_cloud_option(self):
        options = PresetOptionsSchema.model_validate(
            {
                "engine": "metashape",
                "build_point_cloud": True,
            }
        )

        self.assertTrue(options.build_point_cloud)
        self.assertTrue(options.model_dump()["build_point_cloud"])


if __name__ == "__main__":
    unittest.main()
