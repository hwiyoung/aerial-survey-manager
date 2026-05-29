#!/bin/bash
#
# Verify that development changes are represented in production packaging paths.
#

set -euo pipefail

cd "$(dirname "$0")/.."

IO_CSV_PATH="${IO_CSV_PATH:-${AERIAL_IO_CSV_PATH:-}}"
ALLOW_MISSING_IO="false"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --io-csv)
            IO_CSV_PATH="${2:-}"
            shift 2
            ;;
        --allow-missing-io)
            ALLOW_MISSING_IO="true"
            shift
            ;;
        --help|-h)
            cat <<'EOF'
Usage: scripts/check-release-parity.sh [--io-csv /path/to/io.csv]

Checks:
  - dev/prod compose config validity
  - prod API is not GPU-bound
  - prod worker-engine keeps GPU device request
  - storage/export/processing mounts and env are aligned
  - prod Dockerfiles include changed backend/frontend/worker source paths
  - io.csv source is available for packaging
EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

docker compose -f docker-compose.yml config --format json > "$tmp_dir/dev.json"
docker compose -f docker-compose.prod.yml config --format json > "$tmp_dir/prod.json"

python3 - "$tmp_dir/dev.json" "$tmp_dir/prod.json" "$IO_CSV_PATH" "$ALLOW_MISSING_IO" <<'PY'
import json
import os
import sys
from pathlib import Path

dev_path, prod_path, io_csv, allow_missing_io = sys.argv[1:5]
dev = json.load(open(dev_path, encoding="utf-8"))
prod = json.load(open(prod_path, encoding="utf-8"))

failures = []
warnings = []


def env_map(service):
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): "" if v is None else str(v) for k, v in env.items()}
    result = {}
    for item in env:
        if "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def volume_targets(service):
    targets = {}
    for volume in service.get("volumes") or []:
        if isinstance(volume, dict):
            target = volume.get("target")
            if target:
                targets[target] = volume
            continue
        parts = str(volume).split(":")
        if len(parts) >= 2:
            targets[parts[1]] = {
                "source": parts[0],
                "target": parts[1],
                "read_only": "ro" in parts[2:],
            }
    return targets


def has_gpu_request(service):
    return "nvidia" in json.dumps(service.get("deploy", {}), ensure_ascii=False).lower()


required_services = [
    "db",
    "redis",
    "api",
    "frontend",
    "nginx",
    "worker-engine",
    "celery-beat",
    "celery-worker",
    "celery-worker-thumbnail",
    "flower",
    "titiler",
]

for compose_name, compose in (("dev", dev), ("prod", prod)):
    services = compose.get("services", {})
    for name in required_services:
        if name not in services:
            failures.append(f"{compose_name}: missing service {name}")

prod_services = prod.get("services", {})
dev_services = dev.get("services", {})

api = prod_services.get("api", {})
api_env = env_map(api)
for key in ("NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES"):
    if key in api_env:
        failures.append(f"prod api must not set {key}")
if has_gpu_request(api):
    failures.append("prod api must not have an NVIDIA device request")

worker = prod_services.get("worker-engine", {})
worker_env = env_map(worker)
if not has_gpu_request(worker):
    failures.append("prod worker-engine must keep an NVIDIA device request")
for key in ("NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES"):
    if key not in worker_env:
        failures.append(f"prod worker-engine missing {key}")

rw_services = [
    "api",
    "worker-engine",
    "celery-worker",
    "celery-worker-thumbnail",
    "celery-beat",
]
ro_services = ["titiler", "nginx"]

for name in rw_services:
    for compose_name, services in (("dev", dev_services), ("prod", prod_services)):
        service = services.get(name, {})
        env = env_map(service)
        for key, expected in (
            ("LOCAL_STORAGE_PATH", "/data/storage"),
            ("PROCESSING_DATA_PATH", "/data/processing"),
            ("EXPORT_ROOT_PATH", "/data/exports"),
        ):
            if env.get(key) != expected:
                failures.append(
                    f"{compose_name} {name}: {key}={env.get(key)!r}, expected {expected!r}"
                )

    targets = volume_targets(prod_services.get(name, {}))
    for target in (
        "/data/storage/projects",
        "/data/storage/orthomosaic",
        "/data/exports",
    ):
        if target not in targets:
            failures.append(f"prod {name}: missing volume target {target}")
    if name != "celery-beat" and "/data/processing" not in targets:
        failures.append(f"prod {name}: missing volume target /data/processing")

for compose_name, services in (("dev", dev_services), ("prod", prod_services)):
    env = env_map(services.get("api", {}))
    for key, expected in (
        ("MEDIA_STORAGE_ROOT", "/media"),
        ("SYSTEM_STORAGE_PATH", "/"),
        ("FILESYSTEM_ALLOWED_ROOTS", "/media"),
    ):
        if env.get(key) != expected:
            failures.append(
                f"{compose_name} api: {key}={env.get(key)!r}, expected {expected!r}"
            )

for name in ro_services:
    targets = volume_targets(prod_services.get(name, {}))
    for target in (
        "/data/storage/projects",
        "/data/storage/orthomosaic",
        "/data/exports",
    ):
        volume = targets.get(target)
        if not volume:
            failures.append(f"prod {name}: missing read-only volume target {target}")
            continue
        if not volume.get("read_only"):
            failures.append(f"prod {name}: {target} must be read-only")

api_targets = volume_targets(api)
if "/app/data" not in api_targets:
    failures.append("prod api: missing ./data or ./data/regions mount at /app/data")

if io_csv:
    if not Path(io_csv).is_file():
        failures.append(f"io.csv does not exist: {io_csv}")
else:
    candidates = [Path("data/io.csv"), Path("data/regions/io.csv")]
    if not any(path.is_file() for path in candidates):
        message = "io.csv is required for release parity. Set IO_CSV_PATH=/path/to/io.csv."
        if allow_missing_io == "true":
            warnings.append(message)
        else:
            failures.append(message)

dockerfile_checks = {
    "backend/Dockerfile.prod": [
        "COPY . .",
        "RUN python -m compileall -b app/",
        "RUN python -m compileall -b scripts/",
        "COPY entrypoint.sh /entrypoint.sh",
    ],
    "engines/metashape/Dockerfile.prod": [
        "COPY backend/app /app/app",
        "COPY engines/metashape/dags /app/engines/metashape/dags",
        "RUN python3 -m compileall -b /app/app/",
        "RUN python3 -m compileall -b /app/engines/metashape/dags/",
    ],
    "Dockerfile.frontend": [
        "COPY . .",
        "RUN npm run build",
    ],
}

for path, needles in dockerfile_checks.items():
    text = Path(path).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            failures.append(f"{path}: missing packaging rule {needle!r}")

source_paths = [
    "backend/entrypoint.sh",
    "backend/scripts/seed_camera_models.py",
    "backend/app/api/v1/processing.py",
    "backend/app/workers/tasks.py",
    "backend/app/services/processing_router.py",
    "backend/app/models/project.py",
    "src/components/Processing/ProcessingSidebar.jsx",
    "src/components/Upload/UploadWizard.jsx",
    "engines/metashape/dags/metashape/align_photos.py",
    "scripts/systemd-start.sh",
    "scripts/check-gpu-stack.sh",
    "scripts/sync-ortho-result-paths.sh",
]

for path in source_paths:
    if not Path(path).exists():
        failures.append(f"required release source missing: {path}")

if failures:
    print("Release parity check: FAIL")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)

print("Release parity check: PASS")
print("  - dev/prod compose config valid")
print("  - prod API is not GPU-bound")
print("  - prod worker-engine keeps GPU dependency")
print("  - storage/export/processing mounts and env are aligned")
print("  - prod Dockerfiles include backend/frontend/worker changed source paths")
print("  - io.csv source is available for packaging")

if warnings:
    print("Warnings:")
    for item in warnings:
        print(f"  - {item}")
PY
