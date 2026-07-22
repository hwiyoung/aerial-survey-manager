import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from scripts import rename_orthomosaic_files as migration


class _ProjectQuery:
    def __init__(self, projects):
        self.projects = projects

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self.projects


class _ProjectDb:
    def __init__(self, projects):
        self.projects = projects

    def query(self, model):
        return _ProjectQuery(self.projects)


def _project(project_id: str, old_key: str):
    return SimpleNamespace(
        id=UUID(project_id),
        title="테스트",
        region="서울",
        ortho_path=old_key,
        updated_at=None,
    )


class OrthomosaicMigrationTests(unittest.TestCase):
    def test_supported_source_formats_are_detected(self):
        project_id = "11111111-1111-1111-1111-111111111111"

        self.assertEqual(
            migration._source_format(
                "orthomosaic/11111111-1111-1111-1111-111111111111_"
                "orthomosaic_EPSG5186_20260716_123045.tif",
                project_id,
            ),
            "legacy-flat-uuid",
        )
        self.assertEqual(
            migration._source_format(
                f"orthomosaic/{project_id}/서울_테스트_job.tif",
                project_id,
            ),
            "rc-project-directory",
        )
        self.assertIsNone(
            migration._source_format("orthomosaic/서울_테스트.tif", project_id)
        )

    def test_same_flat_target_for_two_projects_gets_numbered_names(self):
        first_id = "11111111-1111-1111-1111-111111111111"
        second_id = "22222222-2222-2222-2222-222222222222"
        first_key = f"orthomosaic/{first_id}/first.tif"
        second_key = f"orthomosaic/{second_id}/second.tif"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for key in (first_key, second_key):
                path = root / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"cog")

            db = _ProjectDb(
                [
                    _project(first_id, first_key),
                    _project(second_id, second_key),
                ]
            )
            with patch.object(migration, "_storage_root", return_value=root):
                plan, skipped = migration._build_plan(db)

        self.assertEqual(skipped, [])
        self.assertEqual(
            [item["new_key"] for item in plan],
            [
                "orthomosaic/서울_테스트.tif",
                "orthomosaic/서울_테스트 (1).tif",
            ],
        )

    def test_rc_directory_with_unreferenced_file_is_skipped(self):
        project_id = "11111111-1111-1111-1111-111111111111"
        old_key = f"orthomosaic/{project_id}/current.tif"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / old_key
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_bytes(b"current")
            (old_path.parent / "older-run.tif").write_bytes(b"older")

            with patch.object(migration, "_storage_root", return_value=root):
                plan, skipped = migration._build_plan(
                    _ProjectDb([_project(project_id, old_key)])
                )

        self.assertEqual(plan, [])
        self.assertEqual(skipped[0]["reason"], "rc-project-directory-has-extra-files")

    def test_existing_flat_db_owner_reserves_name_even_when_file_is_missing(self):
        nested_id = "11111111-1111-1111-1111-111111111111"
        flat_id = "22222222-2222-2222-2222-222222222222"
        old_key = f"orthomosaic/{nested_id}/current.tif"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / old_key
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_bytes(b"current")

            flat_project = _project(flat_id, "orthomosaic/서울_테스트.tif")
            with patch.object(migration, "_storage_root", return_value=root):
                plan, skipped = migration._build_plan(
                    _ProjectDb(
                        [
                            _project(nested_id, old_key),
                            flat_project,
                        ]
                    )
                )

        nested_plan = [
            item for item in plan if item["project_id"] == nested_id
        ]
        self.assertEqual(len(nested_plan), 1)
        self.assertEqual(
            nested_plan[0]["new_key"],
            "orthomosaic/서울_테스트 (1).tif",
        )
        self.assertTrue(
            any(
                item["project_id"] == flat_id
                and item["reason"] == "already-flat-or-unsupported-format"
                for item in skipped
            )
        )

    def test_untracked_flat_files_advance_the_number(self):
        project_id = "11111111-1111-1111-1111-111111111111"
        old_key = f"orthomosaic/{project_id}/current.tif"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / old_key
            old_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.write_bytes(b"current")
            flat_root = root / "orthomosaic"
            (flat_root / "서울_테스트.tif").write_bytes(b"untracked")
            (flat_root / "서울_테스트 (1).tif").write_bytes(b"untracked")

            with patch.object(migration, "_storage_root", return_value=root):
                plan, skipped = migration._build_plan(
                    _ProjectDb([_project(project_id, old_key)])
                )

        self.assertEqual(skipped, [])
        self.assertEqual(
            plan[0]["new_key"],
            "orthomosaic/서울_테스트 (2).tif",
        )
