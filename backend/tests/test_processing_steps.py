import unittest

from app.services.processing_runtime import (
    infer_message_from_step_status,
    progress_from_step_status,
)
from app.services.processing_steps import (
    PROCESSING_STEPS,
    PROJECT_STATE_STEP_RANK,
    processing_step_pairs,
    task_name_for_script,
)


class ProcessingStepTests(unittest.TestCase):
    def test_step_names_are_unique(self):
        script_names = [step.script_name for step in PROCESSING_STEPS]
        task_names = [step.task_name for step in PROCESSING_STEPS]

        self.assertEqual(len(script_names), len(set(script_names)))
        self.assertEqual(len(task_names), len(set(task_names)))

    def test_point_cloud_step_is_optional_and_keeps_pipeline_order(self):
        default_scripts = [
            script_name
            for script_name, _ in processing_step_pairs(build_point_cloud=False)
        ]
        point_cloud_scripts = [
            script_name
            for script_name, _ in processing_step_pairs(build_point_cloud=True)
        ]

        self.assertNotIn("build_point_cloud.py", default_scripts)
        self.assertEqual(
            point_cloud_scripts[1:4],
            ["build_depth_maps.py", "build_point_cloud.py", "build_dem.py"],
        )

    def test_task_name_and_project_checkpoint_rank_share_the_catalog(self):
        self.assertEqual(task_name_for_script("build_dem.py"), "Build DEM")
        self.assertEqual(task_name_for_script("custom.py"), "custom.py")
        self.assertEqual(PROJECT_STATE_STEP_RANK["build_orthomosaic.py"], 5)

    def test_point_cloud_status_is_visible_in_runtime_progress(self):
        step_status = {
            "Align Photos": 100,
            "Build Depth Maps": 100,
            "Build Point Cloud": 40,
            "Build DEM": 0,
        }

        self.assertEqual(
            infer_message_from_step_status(step_status),
            "포인트 클라우드 생성 중...",
        )
        self.assertEqual(progress_from_step_status(step_status), 60)


if __name__ == "__main__":
    unittest.main()
