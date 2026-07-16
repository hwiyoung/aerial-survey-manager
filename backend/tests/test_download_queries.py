import unittest
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.api.v1.download import _latest_completed_job_query


class DownloadQueryTests(unittest.TestCase):
    def test_latest_completed_job_query_is_deterministic_and_limited(self):
        query = _latest_completed_job_query(
            UUID("11111111-1111-1111-1111-111111111111")
        )
        sql = str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("processing_jobs.status = 'completed'", sql)
        self.assertIn("completed_at DESC NULLS LAST", sql)
        self.assertIn("created_at DESC", sql)
        self.assertIn("LIMIT 1", sql)


if __name__ == "__main__":
    unittest.main()
