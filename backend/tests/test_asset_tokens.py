import unittest
from unittest.mock import patch

from app.services import asset_tokens


class AssetTokenTests(unittest.TestCase):
    def test_round_trip_requires_matching_purpose(self):
        with (
            patch.object(
                asset_tokens.settings,
                "JWT_SECRET_KEY",
                "test-secret-at-least-thirty-two-bytes",
            ),
            patch.object(asset_tokens.settings, "JWT_ALGORITHM", "HS256"),
        ):
            token = asset_tokens.create_asset_token(
                project_id="11111111-1111-1111-1111-111111111111",
                object_name=(
                    "projects/11111111-1111-1111-1111-111111111111/"
                    "source/thumbnails/image.jpg"
                ),
                purpose="preview",
            )
            payload = asset_tokens.verify_asset_token(token, purpose="preview")

            self.assertEqual(
                payload["project_id"],
                "11111111-1111-1111-1111-111111111111",
            )
            with self.assertRaises(ValueError):
                asset_tokens.verify_asset_token(token, purpose="tile")


if __name__ == "__main__":
    unittest.main()
