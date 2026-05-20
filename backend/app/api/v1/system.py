"""Runtime system status endpoints."""
import asyncio
import os
import time
from typing import Any

from celery.exceptions import TimeoutError as CeleryTimeoutError
from fastapi import APIRouter, Depends, Response

from app.auth.jwt import get_current_user
from app.config import get_settings
from app.models.user import User
from app.services.system_status import (
    get_gpu_status,
    get_storage_status,
    utc_now_iso,
)

router = APIRouter(prefix="/system", tags=["System"])

_gpu_cache: dict[str, Any] = {"ts": 0.0, "ttl": 0.0, "data": None}


def _mark_gpu_stale(data: dict[str, Any], message: str) -> dict[str, Any]:
    stale_data = dict(data)
    stale_data["stale"] = True
    stale_data["checked_at"] = utc_now_iso()
    stale_data["message"] = message
    return stale_data


def _runtime_gpu_status() -> dict[str, Any]:
    """Return GPU status, preferring API-local nvidia-smi over a busy worker queue."""
    now = time.monotonic()
    if _gpu_cache["data"] and now - _gpu_cache["ts"] < _gpu_cache["ttl"]:
        return _gpu_cache["data"]

    local_data = get_gpu_status()
    if local_data.get("available"):
        local_data["source"] = "api-container"
        _gpu_cache.update({"ts": now, "ttl": 2.0, "data": local_data})
        return local_data

    result = None
    try:
        from app.workers.tasks import inspect_worker_gpu

        result = inspect_worker_gpu.apply_async(
            queue=os.getenv("PROCESSING_ENGINE_QUEUE", "gpu-engine"),
            expires=5,
        )
        data = result.get(timeout=3, disable_sync_subtasks=False)
        if isinstance(data, dict):
            data["source"] = "worker-engine"
            _gpu_cache.update({"ts": now, "ttl": 2.0, "data": data})
            return data
    except CeleryTimeoutError:
        if _gpu_cache["data"] and _gpu_cache["data"].get("devices"):
            data = _mark_gpu_stale(
                _gpu_cache["data"],
                "worker-engine GPU check timed out; showing last GPU status",
            )
            _gpu_cache.update({"ts": now, "ttl": 2.0, "data": data})
            return data
        data = {
            "status": "unknown",
            "available": False,
            "source": "worker-engine",
            "checked_at": utc_now_iso(),
            "devices": [],
            "message": "worker-engine GPU check timed out",
        }
        _gpu_cache.update({"ts": now, "ttl": 5.0, "data": data})
        return data
    except Exception as exc:
        if _gpu_cache["data"] and _gpu_cache["data"].get("devices"):
            data = _mark_gpu_stale(
                _gpu_cache["data"],
                f"GPU status check failed; showing last GPU status: {exc}",
            )
            _gpu_cache.update({"ts": now, "ttl": 2.0, "data": data})
            return data
        data = {
            "status": "unknown",
            "available": False,
            "source": "worker-engine",
            "checked_at": utc_now_iso(),
            "devices": [],
            "message": str(exc),
        }
        _gpu_cache.update({"ts": now, "ttl": 5.0, "data": data})
        return data
    finally:
        if result is not None:
            try:
                result.forget()
            except Exception:
                pass

    data = {
        "status": "unknown",
        "available": False,
        "source": local_data.get("source", "worker-engine"),
        "checked_at": utc_now_iso(),
        "devices": [],
        "message": local_data.get("message") or "worker-engine returned an unexpected GPU status",
    }
    _gpu_cache.update({"ts": now, "ttl": 5.0, "data": data})
    return data


@router.get("/resources")
async def get_system_resources(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """Return a compact runtime resource snapshot for the dashboard sidebar."""
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    gpu_status = await asyncio.to_thread(_runtime_gpu_status)
    storage_paths = [
        ("local_storage", "저장공간", settings.LOCAL_STORAGE_PATH),
        ("processing_data", "처리공간", settings.PROCESSING_DATA_PATH),
        ("orthomosaic", "정사영상", settings.EXPORT_ROOT_PATH),
    ]

    return {
        "timestamp": utc_now_iso(),
        "gpu": gpu_status,
        "storage": [
            get_storage_status(key, label, path)
            for key, label, path in storage_paths
        ],
    }
