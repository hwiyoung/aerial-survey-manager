import inspect
import unittest

from fastapi.routing import APIRoute

from app.api.v1 import filesystem, projects, router as api_router, upload
from app.auth.jwt import get_current_user


def _route_dependency_calls(router, path: str, method: str):
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method.upper() in route.methods
    )
    return {dependency.call for dependency in route.dependant.dependencies}


class RoutePermissionContractTests(unittest.TestCase):
    def assert_authenticated(self, router, path: str, method: str):
        dependency_calls = _route_dependency_calls(router, path, method)
        self.assertIn(get_current_user, dependency_calls)

    def test_project_creation_requires_only_the_authenticated_account(self):
        self.assert_authenticated(projects.router, "/projects", "POST")

    def test_server_filesystem_access_uses_the_authenticated_account(self):
        self.assert_authenticated(filesystem.router, "/filesystem/roots", "GET")
        self.assert_authenticated(filesystem.router, "/filesystem/browse", "GET")
        self.assert_authenticated(filesystem.router, "/filesystem/read-text", "GET")

    def test_server_local_import_uses_the_authenticated_account(self):
        self.assert_authenticated(
            upload.router,
            "/upload/projects/{project_id}/local-import",
            "POST",
        )

    def test_multi_account_management_routes_are_not_mounted(self):
        mounted_paths = {
            route.path
            for route in api_router.routes
            if isinstance(route, APIRoute)
        }
        self.assertFalse(any(path.startswith("/users") for path in mounted_paths))
        self.assertFalse(any(path.startswith("/organizations") for path in mounted_paths))
        self.assertFalse(any(path.startswith("/permissions") for path in mounted_paths))

    def test_multipart_completion_isolates_each_file_with_a_savepoint(self):
        completion_source = inspect.getsource(upload.complete_multipart_upload)

        self.assertIn("savepoint = await db.begin_nested()", completion_source)
        self.assertIn("await db.flush()", completion_source)
        self.assertIn("await savepoint.commit()", completion_source)
        self.assertIn("await savepoint.rollback()", completion_source)


if __name__ == "__main__":
    unittest.main()
