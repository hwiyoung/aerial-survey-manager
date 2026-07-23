import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from app.api.v1 import projects
from app.schemas.project import ProjectCreate


class _RecordingDb:
    def __init__(self):
        self.events = []

    def add(self, _project):
        self.events.append("add")

    async def flush(self):
        self.events.append("flush")

    async def refresh(self, project):
        project.id = UUID("33333333-3333-3333-3333-333333333333")
        self.events.append("refresh")

    async def commit(self):
        self.events.append("commit")


class ProjectCreationTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_is_committed_before_response_is_built(self):
        db = _RecordingDb()
        current_user = SimpleNamespace(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            organization_id=UUID("22222222-2222-2222-2222-222222222222"),
        )
        response = object()

        def build_response(_project):
            db.events.append("response")
            return response

        with (
            patch.object(
                projects,
                "ensure_organization_quota",
                new=AsyncMock(),
            ),
            patch.object(projects, "log_audit_event", new=Mock()),
            patch.object(
                projects,
                "_build_project_response",
                side_effect=build_response,
            ),
        ):
            result = await projects.create_project(
                ProjectCreate(title="Commit ordering"),
                current_user,
                db,
            )

        self.assertIs(result, response)
        self.assertEqual(
            db.events,
            ["add", "flush", "refresh", "commit", "response"],
        )


if __name__ == "__main__":
    unittest.main()
