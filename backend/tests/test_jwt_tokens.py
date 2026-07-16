import unittest
from datetime import timedelta

from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.config import Settings


class JwtTokenTests(unittest.TestCase):
    def test_password_hash_round_trip_and_invalid_hash(self):
        password = "A-strong-test-password"
        hashed = hash_password(password)

        self.assertTrue(hashed.startswith("$2"))
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("wrong-password", hashed))
        self.assertFalse(verify_password(password, "not-a-bcrypt-hash"))

    def test_access_token_round_trip(self):
        token = create_access_token("user-123", "manager")
        payload = verify_token(token, "access")

        self.assertEqual(payload["sub"], "user-123")
        self.assertEqual(payload["role"], "manager")
        self.assertEqual(payload["type"], "access")

    def test_refresh_token_type_is_enforced(self):
        token = create_refresh_token("user-123")
        with self.assertRaises(HTTPException):
            verify_token(token, "access")

    def test_expired_token_is_rejected(self):
        token = create_access_token(
            "user-123",
            "user",
            expires_delta=timedelta(seconds=-1),
        )
        with self.assertRaises(HTTPException):
            verify_token(token, "access")

    def test_deployment_rejects_weak_or_placeholder_secret(self):
        with self.assertRaises(ValidationError):
            Settings(
                JWT_SECRET_KEY="short",
                ALLOW_WEAK_JWT_SECRET=False,
                _env_file=None,
            )
        with self.assertRaises(ValidationError):
            Settings(
                JWT_SECRET_KEY="CHANGE_THIS_TO_AT_LEAST_32_CHARACTER_SECRET_KEY",
                ALLOW_WEAK_JWT_SECRET=False,
                _env_file=None,
            )

    def test_deployment_accepts_strong_secret(self):
        settings = Settings(
            JWT_SECRET_KEY="7bdeef62d556a98d96fb526f49fb765db5d96fdf93f533170b148a09f3142b60",
            ALLOW_WEAK_JWT_SECRET=False,
            _env_file=None,
        )
        self.assertFalse(settings.ALLOW_WEAK_JWT_SECRET)


if __name__ == "__main__":
    unittest.main()
