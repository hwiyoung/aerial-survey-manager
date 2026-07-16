import unittest
from unittest.mock import Mock, patch

from app.api.v1.system import _gpu_worker_probe_readiness


class GpuWorkerProbeReadinessTests(unittest.TestCase):
    def _celery_app(self, *, queues=None, active=None, reserved=None):
        inspector = Mock()
        inspector.active_queues.return_value = queues
        inspector.active.return_value = active
        inspector.reserved.return_value = reserved
        celery_app = Mock()
        celery_app.control.inspect.return_value = inspector
        return celery_app

    @patch("redis.Redis.from_url")
    def test_missing_worker_does_not_check_or_publish_queue(self, redis_from_url):
        ready, message = _gpu_worker_probe_readiness(
            self._celery_app(queues={}),
            "gpu-engine",
            "redis://example/0",
        )

        self.assertFalse(ready)
        self.assertIn("not available", message)
        redis_from_url.assert_not_called()

    @patch("redis.Redis.from_url")
    def test_busy_worker_is_not_probed(self, redis_from_url):
        worker = "worker-engine@example"
        ready, message = _gpu_worker_probe_readiness(
            self._celery_app(
                queues={worker: [{"name": "gpu-engine"}]},
                active={worker: [{"id": "processing-task"}]},
                reserved={worker: []},
            ),
            "gpu-engine",
            "redis://example/0",
        )

        self.assertFalse(ready)
        self.assertIn("busy", message)
        redis_from_url.assert_not_called()

    @patch("redis.Redis.from_url")
    def test_nonempty_queue_is_not_probed(self, redis_from_url):
        worker = "worker-engine@example"
        redis_from_url.return_value.llen.return_value = 3
        ready, message = _gpu_worker_probe_readiness(
            self._celery_app(
                queues={worker: [{"name": "gpu-engine"}]},
                active={worker: []},
                reserved={worker: []},
            ),
            "gpu-engine",
            "redis://example/0",
        )

        self.assertFalse(ready)
        self.assertIn("3 pending", message)

    @patch("redis.Redis.from_url")
    def test_idle_worker_with_empty_queue_can_be_probed(self, redis_from_url):
        worker = "worker-engine@example"
        redis_from_url.return_value.llen.return_value = 0
        ready, message = _gpu_worker_probe_readiness(
            self._celery_app(
                queues={worker: [{"name": "gpu-engine"}]},
                active={worker: []},
                reserved={worker: []},
            ),
            "gpu-engine",
            "redis://example/0",
        )

        self.assertTrue(ready)
        self.assertIn("ready", message)


if __name__ == "__main__":
    unittest.main()
