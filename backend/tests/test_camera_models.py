import unittest
from types import SimpleNamespace
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1.upload import FileInfo, LocalImportRequest, MultipartInitRequest
from app.models.project import CameraModel
from app.schemas.project import CameraModelCreate
from app.services.camera_models import (
    apply_camera_model_access_scope,
    can_manage_camera_model,
    custom_model_organization_id,
    normalize_camera_model_name,
)


ORG_A = UUID("11111111-1111-1111-1111-111111111111")
ORG_B = UUID("22222222-2222-2222-2222-222222222222")
CAMERA_ID = UUID("33333333-3333-3333-3333-333333333333")


def _user(*, organization_id=None, role="user"):
    return SimpleNamespace(organization_id=organization_id, role=role)


def _camera(*, organization_id=None, is_custom=False):
    return SimpleNamespace(
        organization_id=organization_id,
        is_custom=is_custom,
    )


class CameraModelScopeTests(unittest.TestCase):
    def _compile(self, user) -> str:
        query = apply_camera_model_access_scope(select(CameraModel), user)
        return str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

    def test_organization_user_sees_public_and_same_org_custom_models(self):
        sql = self._compile(_user(organization_id=ORG_A))

        self.assertIn("camera_models.organization_id IS NULL", sql)
        self.assertIn("camera_models.is_custom IS false", sql)
        self.assertIn(str(ORG_A), sql)
        self.assertIn("camera_models.is_custom IS true", sql)

    def test_unorganized_user_sees_only_public_standard_models(self):
        sql = self._compile(_user())

        self.assertIn("camera_models.organization_id IS NULL", sql)
        self.assertIn("camera_models.is_custom IS false", sql)
        self.assertNotIn("camera_models.is_custom IS true", sql)

    def test_admin_scope_is_unfiltered(self):
        sql = self._compile(_user(role="admin"))
        self.assertNotIn("WHERE", sql)

    def test_only_same_org_custom_models_are_user_managed(self):
        user = _user(organization_id=ORG_A)

        self.assertTrue(
            can_manage_camera_model(
                _camera(organization_id=ORG_A, is_custom=True),
                user,
            )
        )
        self.assertFalse(
            can_manage_camera_model(
                _camera(organization_id=ORG_B, is_custom=True),
                user,
            )
        )
        self.assertFalse(
            can_manage_camera_model(
                _camera(organization_id=None, is_custom=False),
                user,
            )
        )
        self.assertFalse(
            can_manage_camera_model(
                _camera(organization_id=None, is_custom=True),
                _user(),
            )
        )

    def test_admin_can_manage_any_camera_model(self):
        self.assertTrue(
            can_manage_camera_model(
                _camera(organization_id=ORG_B, is_custom=True),
                _user(role="admin"),
            )
        )


class CameraModelContractTests(unittest.TestCase):
    def test_names_are_trimmed_and_empty_names_are_rejected(self):
        self.assertEqual(normalize_camera_model_name("  Camera A  "), "Camera A")
        model = CameraModelCreate(name="  Camera A  ")
        self.assertEqual(model.name, "Camera A")

        with self.assertRaises(ValueError):
            normalize_camera_model_name("   ")
        with self.assertRaises(ValidationError):
            CameraModelCreate(name="   ")

    def test_custom_models_require_organization_membership(self):
        self.assertEqual(
            custom_model_organization_id(_user(organization_id=ORG_A)),
            ORG_A,
        )
        with self.assertRaisesRegex(ValueError, "Organization membership"):
            custom_model_organization_id(_user())

    def test_upload_contract_uses_camera_uuid(self):
        local_request = LocalImportRequest(
            source_dir="/data/images",
            camera_model_id=str(CAMERA_ID),
        )
        multipart_request = MultipartInitRequest(
            files=[FileInfo(filename="image.tif", size=1)],
            camera_model_id=str(CAMERA_ID),
        )

        self.assertEqual(local_request.camera_model_id, CAMERA_ID)
        self.assertEqual(multipart_request.camera_model_id, CAMERA_ID)

    def test_legacy_camera_name_upload_contract_is_rejected(self):
        with self.assertRaises(ValidationError):
            LocalImportRequest(
                source_dir="/data/images",
                camera_model_name="Camera A",
            )
        with self.assertRaises(ValidationError):
            MultipartInitRequest(
                files=[FileInfo(filename="image.tif", size=1)],
                camera_model_name="Camera A",
            )


if __name__ == "__main__":
    unittest.main()
