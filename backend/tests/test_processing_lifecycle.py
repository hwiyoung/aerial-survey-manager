import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.processing_lifecycle import (
    processing_options_for_job,
    stale_processing_job_reason,
    startup_recovery_in_grace_period,
)


class ProcessingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 16, 12, 0, 0)

    def test_fresh_queued_job_is_not_stale(self):
        reason = stale_processing_job_reason(
            status="queued",
            created_at=self.now - timedelta(minutes=1),
            queued_at=self.now - timedelta(minutes=1),
            started_at=None,
            now=self.now,
        )
        self.assertIsNone(reason)

    def test_queued_job_becomes_stale_after_six_hours(self):
        reason = stale_processing_job_reason(
            status="queued",
            created_at=self.now - timedelta(hours=7),
            queued_at=self.now - timedelta(hours=7),
            started_at=None,
            now=self.now,
        )
        self.assertIn("6시간", reason)

    def test_scheduled_job_is_not_automatically_replaced(self):
        reason = stale_processing_job_reason(
            status="scheduled",
            created_at=self.now - timedelta(days=2),
            queued_at=None,
            started_at=None,
            now=self.now,
        )
        self.assertIsNone(reason)

    def test_current_terminal_runtime_state_is_stale(self):
        reason = stale_processing_job_reason(
            status="processing",
            created_at=self.now - timedelta(minutes=10),
            queued_at=self.now - timedelta(minutes=10),
            started_at=self.now - timedelta(minutes=9),
            runtime_status="error",
            now=self.now,
        )
        self.assertIn("error", reason)

    def test_force_restart_is_explicit(self):
        reason = stale_processing_job_reason(
            status="scheduled",
            created_at=self.now,
            queued_at=None,
            started_at=None,
            force_restart=True,
            now=self.now,
        )
        self.assertIn("강제 재시작", reason)

    def test_startup_recovery_keeps_recent_job(self):
        self.assertTrue(
            startup_recovery_in_grace_period(
                created_at=self.now - timedelta(minutes=10),
                started_at=self.now - timedelta(minutes=9),
                now=self.now,
            )
        )
        self.assertFalse(
            startup_recovery_in_grace_period(
                created_at=self.now - timedelta(hours=1),
                started_at=self.now - timedelta(hours=1),
                now=self.now,
            )
        )

    def test_scheduled_job_preserves_advanced_processing_options(self):
        job = SimpleNamespace(
            engine="metashape",
            gsd=3.0,
            output_crs="EPSG:5187",
            output_format="GeoTiff",
            process_mode="High",
            processing_options={
                "eo_only_align": False,
                "build_point_cloud": True,
                "resume_checkpoint": False,
            },
        )

        options = processing_options_for_job(job)

        self.assertFalse(options["eo_only_align"])
        self.assertTrue(options["build_point_cloud"])
        self.assertFalse(options["resume_checkpoint"])
        self.assertEqual(options["process_mode"], "High")

    def test_job_columns_override_stale_option_snapshot(self):
        job = SimpleNamespace(
            engine="metashape",
            gsd=5.0,
            output_crs="EPSG:5186",
            output_format="GeoTiff",
            process_mode="Normal",
            processing_options={
                "engine": "legacy-engine",
                "gsd": 99,
                "build_point_cloud": True,
            },
        )

        options = processing_options_for_job(job)

        self.assertEqual(options["engine"], "metashape")
        self.assertEqual(options["gsd"], 5.0)
        self.assertTrue(options["build_point_cloud"])


if __name__ == "__main__":
    unittest.main()
