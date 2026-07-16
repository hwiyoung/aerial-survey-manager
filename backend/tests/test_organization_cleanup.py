import unittest
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.api.v1.organizations import _delete_organization_camera_models


ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMERA_MODEL_ID = UUID("22222222-2222-2222-2222-222222222222")


class _ScalarCollection:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, values=()):
        self.values = values

    def scalars(self):
        return _ScalarCollection(self.values)


class _RecordingDb:
    def __init__(self, camera_model_ids):
        self.camera_model_ids = camera_model_ids
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(self.camera_model_ids)
        return _Result()


def _compile(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class OrganizationCameraCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_references_are_cleared_before_camera_models_are_deleted(self):
        db = _RecordingDb([CAMERA_MODEL_ID])

        removed_count = await _delete_organization_camera_models(
            ORGANIZATION_ID,
            db,
        )

        self.assertEqual(removed_count, 1)
        self.assertEqual(len(db.statements), 3)

        select_sql, update_sql, delete_sql = map(_compile, db.statements)
        self.assertIn("FOR UPDATE", select_sql)
        self.assertIn("UPDATE images SET camera_model_id=NULL", update_sql)
        self.assertIn(str(CAMERA_MODEL_ID), update_sql)
        self.assertIn("DELETE FROM camera_models", delete_sql)
        self.assertIn(str(CAMERA_MODEL_ID), delete_sql)

    async def test_no_camera_models_require_no_reference_updates(self):
        db = _RecordingDb([])

        removed_count = await _delete_organization_camera_models(
            ORGANIZATION_ID,
            db,
        )

        self.assertEqual(removed_count, 0)
        self.assertEqual(len(db.statements), 1)


if __name__ == "__main__":
    unittest.main()
