import unittest
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.auth.jwt import (
    PermissionChecker,
    apply_project_access_scope,
    resolve_project_permission,
)
from app.models.project import Project


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _SequenceDb:
    def __init__(self, *values):
        self.values = iter(values)

    async def execute(self, _query):
        return _ScalarResult(next(self.values))


def _user(*, user_id: str, organization_id=None, role="user"):
    return SimpleNamespace(
        id=UUID(user_id),
        organization_id=organization_id,
        role=role,
    )


def _project(*, owner_id: str, organization_id=None):
    return SimpleNamespace(
        owner_id=UUID(owner_id),
        organization_id=organization_id,
    )


class ProjectAccessScopeTests(unittest.TestCase):
    def test_unorganized_account_scope_requires_ownership(self):
        user = _user(user_id="11111111-1111-1111-1111-111111111111")
        query = apply_project_access_scope(select(Project), user)
        sql = str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("projects.organization_id IS NULL", sql)
        self.assertIn("projects.owner_id =", sql)
        self.assertNotIn("project_permissions", sql)

    def test_same_organization_has_full_project_access(self):
        user = _user(
            user_id="11111111-1111-1111-1111-111111111111",
            organization_id=UUID("33333333-3333-3333-3333-333333333333"),
        )
        project = _project(
            owner_id="22222222-2222-2222-2222-222222222222",
            organization_id=UUID("33333333-3333-3333-3333-333333333333"),
        )

        self.assertEqual(resolve_project_permission(project, user), "admin")

    def test_null_organizations_do_not_imply_shared_access(self):
        user = _user(user_id="11111111-1111-1111-1111-111111111111")
        project = _project(owner_id="22222222-2222-2222-2222-222222222222")

        self.assertIsNone(resolve_project_permission(project, user))


class PermissionCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unorganized_account_cannot_edit_unowned_project(self):
        user = _user(user_id="11111111-1111-1111-1111-111111111111")
        project = _project(owner_id="22222222-2222-2222-2222-222222222222")
        checker = PermissionChecker("edit")

        allowed = await checker.check(
            "33333333-3333-3333-3333-333333333333",
            user,
            _SequenceDb(project),
        )

        self.assertFalse(allowed)

    async def test_same_organization_can_delete_project(self):
        organization_id = UUID("33333333-3333-3333-3333-333333333333")
        user = _user(
            user_id="11111111-1111-1111-1111-111111111111",
            organization_id=organization_id,
        )
        project = _project(
            owner_id="22222222-2222-2222-2222-222222222222",
            organization_id=organization_id,
        )
        checker = PermissionChecker("admin")

        allowed = await checker.check(
            "33333333-3333-3333-3333-333333333333",
            user,
            _SequenceDb(project),
        )

        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
