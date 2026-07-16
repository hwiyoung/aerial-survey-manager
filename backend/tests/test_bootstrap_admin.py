import unittest

from scripts.bootstrap_admin import (
    MIN_INITIAL_ACCOUNT_PASSWORD_LENGTH,
    load_initial_account_bootstrap_config,
)


class InitialAccountBootstrapConfigTests(unittest.TestCase):
    def test_requires_credentials_for_empty_install(self):
        with self.assertRaisesRegex(ValueError, "ADMIN_EMAIL, ADMIN_PASSWORD"):
            load_initial_account_bootstrap_config({})

    def test_rejects_short_production_password(self):
        with self.assertRaisesRegex(
            ValueError,
            str(MIN_INITIAL_ACCOUNT_PASSWORD_LENGTH),
        ):
            load_initial_account_bootstrap_config(
                {"ADMIN_EMAIL": "admin", "ADMIN_PASSWORD": "siqms"}
            )

    def test_allows_explicit_weak_development_password(self):
        config = load_initial_account_bootstrap_config(
            {
                "ADMIN_EMAIL": "admin",
                "ADMIN_PASSWORD": "siqms",
                "ALLOW_WEAK_ADMIN_PASSWORD": "true",
            }
        )
        self.assertEqual(config.email, "admin")
        self.assertEqual(config.password, "siqms")

    def test_accepts_strong_deployment_credentials(self):
        config = load_initial_account_bootstrap_config(
            {
                "ADMIN_EMAIL": "ops-admin",
                "ADMIN_PASSWORD": "a-strong-initial-password",
                "ADMIN_NAME": "운영 관리자",
            }
        )
        self.assertEqual(config.email, "ops-admin")
        self.assertEqual(config.name, "운영 관리자")

    def test_rejects_packaged_placeholder_password(self):
        with self.assertRaisesRegex(ValueError, "placeholder"):
            load_initial_account_bootstrap_config(
                {
                    "ADMIN_EMAIL": "admin",
                    "ADMIN_PASSWORD": "CHANGE_THIS_TO_STRONG_INITIAL_ADMIN_PASSWORD",
                }
            )


if __name__ == "__main__":
    unittest.main()
