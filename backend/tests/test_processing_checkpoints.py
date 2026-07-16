import json
import tempfile
import unittest
from pathlib import Path

from app.services.processing_checkpoints import (
    project_checkpoint_covers,
    summarize_processing_restart,
)


class ProcessingCheckpointTests(unittest.TestCase):
    def _write_manifest(self, work_dir: Path, steps: dict) -> None:
        (work_dir / "processing_manifest.json").write_text(
            json.dumps({"steps": steps}),
            encoding="utf-8",
        )

    def _write_project_checkpoint(self, work_dir: Path, script_name: str) -> None:
        checkpoint_dir = work_dir / ".processing_checkpoint"
        checkpoint_dir.mkdir()
        (checkpoint_dir / "project.psx").write_bytes(b"project")
        (checkpoint_dir / "project.files").mkdir()
        (checkpoint_dir / "step.txt").write_text(script_name, encoding="utf-8")

    def test_missing_manifest_has_no_restart_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = summarize_processing_restart(Path(temp_dir))

        self.assertFalse(summary["manifest_exists"])
        self.assertFalse(summary["can_resume"])
        self.assertEqual(summary["completed_steps"], [])

    def test_later_project_checkpoint_covers_earlier_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            self._write_project_checkpoint(work_dir, "build_dem.py")

            self.assertTrue(project_checkpoint_covers(work_dir, "align_photos.py"))
            self.assertTrue(project_checkpoint_covers(work_dir, "build_dem.py"))
            self.assertFalse(project_checkpoint_covers(work_dir, "build_orthomosaic.py"))

    def test_summary_reports_reusable_and_failed_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            self._write_project_checkpoint(work_dir, "build_dem.py")
            self._write_manifest(
                work_dir,
                {
                    "align_photos.py": {
                        "status": "completed",
                        "completed_at": "2026-07-16T12:00:00",
                    },
                    "export_orthomosaic.py": {
                        "status": "failed",
                        "error_code": "EXPORT_FAILED",
                        "error_message": "failed",
                    },
                },
            )

            summary = summarize_processing_restart(work_dir)

        self.assertTrue(summary["can_resume"])
        self.assertEqual(summary["completed_steps"][0]["label"], "이미지 정렬")
        self.assertEqual(summary["failed_step"]["error_code"], "EXPORT_FAILED")
        self.assertEqual(summary["next_step"]["script"], "export_orthomosaic.py")

    def test_export_requires_its_output_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            self._write_manifest(
                work_dir,
                {"export_orthomosaic.py": {"status": "completed"}},
            )

            without_result = summarize_processing_restart(work_dir)
            (work_dir / "result.tif").write_bytes(b"raster")
            with_result = summarize_processing_restart(work_dir)

        self.assertFalse(without_result["can_resume"])
        self.assertTrue(with_result["can_resume"])


if __name__ == "__main__":
    unittest.main()
