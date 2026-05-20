"""Lightweight runtime status helpers for the API and workers."""
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_from_available_percent(available_percent: Optional[float]) -> str:
    if available_percent is None:
        return "unknown"
    if available_percent <= 5:
        return "critical"
    if available_percent <= 15:
        return "warning"
    return "ok"


def _gpu_device_status(utilization: Optional[float], memory_used_percent: Optional[float]) -> str:
    """Classify whether a visible GPU is currently available for more work."""
    signals = [
        value for value in (utilization, memory_used_percent)
        if value is not None
    ]
    if not signals:
        return "unknown"
    if any(value >= 95 for value in signals):
        return "critical"
    if any(value >= 80 for value in signals):
        return "warning"
    return "ok"


def _rollup_status(statuses: list[str]) -> str:
    if "critical" in statuses:
        return "critical"
    if "warning" in statuses:
        return "warning"
    if "ok" in statuses:
        return "ok"
    return "unknown"


def get_storage_status(key: str, label: str, path: str) -> dict[str, Any]:
    """Return filesystem capacity for a mounted application path."""
    resolved_path = str(Path(path))
    try:
        stat = os.statvfs(resolved_path)
        total = stat.f_blocks * stat.f_frsize
        available = stat.f_bavail * stat.f_frsize
        used = max(0, total - available)
        used_percent = round((used / total) * 100, 1) if total else None
        available_percent = round((available / total) * 100, 1) if total else None
        return {
            "key": key,
            "label": label,
            "path": resolved_path,
            "status": _status_from_available_percent(available_percent),
            "exists": True,
            "total_bytes": total,
            "used_bytes": used,
            "available_bytes": available,
            "used_percent": used_percent,
            "available_percent": available_percent,
        }
    except (OSError, PermissionError) as exc:
        return {
            "key": key,
            "label": label,
            "path": resolved_path,
            "status": "unknown",
            "exists": Path(resolved_path).exists(),
            "total_bytes": None,
            "used_bytes": None,
            "available_bytes": None,
            "used_percent": None,
            "available_percent": None,
            "message": str(exc),
        }


def get_gpu_status() -> dict[str, Any]:
    """Return GPU status from the container where this helper is executed."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {
            "status": "unknown",
            "available": False,
            "source": "nvidia-smi",
            "checked_at": utc_now_iso(),
            "devices": [],
            "message": "nvidia-smi not found",
        }

    query = [
        nvidia_smi,
        "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(query, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return {
            "status": "unknown",
            "available": False,
            "source": "nvidia-smi",
            "checked_at": utc_now_iso(),
            "devices": [],
            "message": "nvidia-smi timed out",
        }

    if result.returncode != 0:
        return {
            "status": "critical",
            "available": False,
            "source": "nvidia-smi",
            "checked_at": utc_now_iso(),
            "devices": [],
            "message": result.stderr.strip() or "nvidia-smi failed",
        }

    devices = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            total_memory = int(float(parts[2])) * 1024 * 1024
            used_memory = int(float(parts[3])) * 1024 * 1024
            utilization = float(parts[4])
            temperature = float(parts[5])
            memory_used_percent = (
                round((used_memory / total_memory) * 100, 1)
                if total_memory
                else None
            )
        except ValueError:
            total_memory = None
            used_memory = None
            utilization = None
            temperature = None
            memory_used_percent = None
        status = _gpu_device_status(utilization, memory_used_percent)
        devices.append({
            "index": parts[0],
            "name": parts[1],
            "memory_total_bytes": total_memory,
            "memory_used_bytes": used_memory,
            "memory_used_percent": memory_used_percent,
            "utilization_percent": utilization,
            "temperature_c": temperature,
            "status": status,
        })

    device_statuses = [device.get("status", "unknown") for device in devices]
    return {
        "status": _rollup_status(device_statuses) if devices else "unknown",
        "available": bool(devices),
        "source": "nvidia-smi",
        "checked_at": utc_now_iso(),
        "devices": devices,
        "message": f"{len(devices)} GPU(s) detected" if devices else "No GPUs detected",
    }
