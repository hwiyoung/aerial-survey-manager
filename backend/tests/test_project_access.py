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
    def test_unorganized_user_scope_requires_ownership_or_explicit_share(self):
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
        self.assertIn("project_permissions.user_id =", sql)

    def test_null_organizations_do_not_imply_shared_view_permission(self):
        user = _user(user_id="11111111-1111-1111-1111-111111111111")
        project = _project(owner_id="22222222-2222-2222-2222-222222222222")

        self.assertIsNone(resolve_project_permission(project, user))
        self.assertEqual(
            resolve_project_permission(project, user, "view"),
            "view",
        )


class PermissionCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unorganized_user_cannot_view_unshared_project(self):
        user = _user(user_id="11111111-1111-1111-1111-111111111111")
        project = _project(owner_id="22222222-2222-2222-2222-222222222222")
        checker = PermissionChecker("view")

        allowed = await checker.check(
            "33333333-3333-3333-3333-333333333333",
            user,
            _SequenceDb(project, None),
        )

        self.assertFalse(allowed)

    async def test_unorganized_user_can_view_explicitly_shared_project(self):
        user = _user(user_id="11111111-1111-1111-1111-111111111111")
        project = _project(owner_id="22222222-2222-2222-2222-222222222222")
        permission = SimpleNamespace(permission="view")
        checker = PermissionChecker("view")

        allowed = await checker.check(
            "33333333-3333-3333-3333-333333333333",
            user,
            _SequenceDb(project, permission),
        )

        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
