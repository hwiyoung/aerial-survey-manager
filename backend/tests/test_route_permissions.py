import unittest

from fastapi.routing import APIRoute

from app.api.v1 import filesystem, projects, upload
from app.auth.jwt import get_current_active_manager, get_current_user


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
    def assert_manager_only(self, router, path: str, method: str):
        dependency_calls = _route_dependency_calls(router, path, method)
        self.assertIn(get_current_active_manager, dependency_calls)
        self.assertNotIn(get_current_user, dependency_calls)

    def test_project_creation_requires_manager_role(self):
        self.assert_manager_only(projects.router, "/projects", "POST")

    def test_server_filesystem_access_requires_manager_role(self):
        self.assert_manager_only(filesystem.router, "/filesystem/roots", "GET")
        self.assert_manager_only(filesystem.router, "/filesystem/browse", "GET")
        self.assert_manager_only(filesystem.router, "/filesystem/read-text", "GET")

    def test_server_local_import_requires_manager_role(self):
        self.assert_manager_only(
            upload.router,
            "/upload/projects/{project_id}/local-import",
            "POST",
        )


if __name__ == "__main__":
    unittest.main()
