"""Shared processing-job lifecycle rules.

Keep time-based decisions here so API requests and startup recovery do not
silently disagree about whether a job is still valid.
"""
from datetime import datetime, timedelta


ACTIVE_PROCESSING_STATUSES = frozenset({"scheduled", "queued", "processing"})
QUEUED_STALE_AFTER = timedelta(hours=6)
PROCESSING_STALE_AFTER = timedelta(hours=24)
STARTUP_RECOVERY_GRACE = timedelta(minutes=15)


def stale_processing_job_reason(
    *,
    status: str,
    created_at: datetime | None,
    queued_at: datetime | None,
    started_at: datetime | None,
    runtime_status: str | None = None,
    force_restart: bool = False,
    now: datetime | None = None,
) -> str | None:
    """Return a user-facing reason only when an active job is safe to replace."""
    if force_restart:
        return "사용자가 강제 재시작을 요청했습니다"

    if runtime_status in {"error", "failed", "cancelled"}:
        return f"현재 작업의 처리 상태 파일이 {runtime_status} 상태입니다"

    now = now or datetime.utcnow()
    if status == "queued":
        reference = queued_at or created_at
        if reference and now - reference > QUEUED_STALE_AFTER:
            return "작업이 6시간 이상 대기열에서 시작되지 않았습니다"
        return None

    if status == "processing" and started_at:
        if now - started_at > PROCESSING_STALE_AFTER:
            return "작업이 24시간 이상 진행 중이었습니다"

    return None


def startup_recovery_in_grace_period(
    *,
    created_at: datetime | None,
    started_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Protect newly claimed tasks while API and workers are still starting."""
    reference = started_at or created_at
    if reference is None:
        return True
    return (now or datetime.utcnow()) - reference <= STARTUP_RECOVERY_GRACE
