"""Workers exports."""
from app.workers.tasks import (
    celery_app,
    process_orthophoto,
    generate_thumbnail,
    regenerate_missing_thumbnails,
)

__all__ = [
    "celery_app",
    "process_orthophoto",
    "generate_thumbnail",
    "regenerate_missing_thumbnails",
]
