"""Sync database session utilities for Celery workers."""
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings

_sync_engine = None
_engine_lock = threading.Lock()


def _get_sync_engine():
    """Get or create the sync SQLAlchemy engine (thread-safe singleton)."""
    global _sync_engine
    if _sync_engine is None:
        with _engine_lock:
            if _sync_engine is None:
                settings = get_settings()
                sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
                _sync_engine = create_engine(sync_db_url)
    return _sync_engine


@contextmanager
def sync_db_session():
    """Context manager for sync database sessions in Celery tasks.

    Usage:
        with sync_db_session() as db:
            project = db.query(Project).filter(...).first()
    """
    engine = _get_sync_engine()
    with Session(engine) as session:
        yield session
