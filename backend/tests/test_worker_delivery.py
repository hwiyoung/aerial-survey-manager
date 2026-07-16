import unittest

from app.workers.tasks import _is_processing_redelivery


class WorkerDeliveryTests(unittest.TestCase):
    def test_same_task_can_reclaim_a_redelivered_processing_job(self):
        self.assertTrue(
            _is_processing_redelivery(
                job_status="processing",
                expected_task_id="task-1",
                request_task_id="task-1",
                delivery_info={"redelivered": True},
            )
        )

    def test_normal_duplicate_or_different_task_cannot_reclaim(self):
        self.assertFalse(
            _is_processing_redelivery(
                job_status="processing",
                expected_task_id="task-1",
                request_task_id="task-1",
                delivery_info={"redelivered": False},
            )
        )
        self.assertFalse(
            _is_processing_redelivery(
                job_status="processing",
                expected_task_id="task-1",
                request_task_id="task-2",
                delivery_info={"redelivered": True},
            )
        )


if __name__ == "__main__":
    unittest.main()
