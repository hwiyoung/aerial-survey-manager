#!/bin/bash
# Verify that the deployed frontend, API, and browser cache policy are aligned.

set -euo pipefail

cd "$(dirname "$0")/.."

base_url="${1:-http://127.0.0.1:${AERIAL_WEB_PORT:-18100}}"
base_url="${base_url%/}"
expected_version="$(tr -d '[:space:]' < VERSION)"
cache_bust="$(date +%s)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

curl -fsS "$base_url/health?check=$cache_bust" > "$tmp_dir/health.json"
curl -fsS -H 'Cache-Control: no-cache' \
    "$base_url/version.json?check=$cache_bust" > "$tmp_dir/frontend.json"
curl -fsS -D "$tmp_dir/index.headers" -o "$tmp_dir/index.html" \
    -H 'Cache-Control: no-cache' "$base_url/?check=$cache_bust"

python3 - "$tmp_dir/health.json" "$tmp_dir/frontend.json" "$expected_version" <<'PY'
import json
import sys

health_path, frontend_path, expected = sys.argv[1:]
health = json.load(open(health_path, encoding="utf-8"))
frontend = json.load(open(frontend_path, encoding="utf-8"))
api_version = str(health.get("version") or "")
frontend_version = str(frontend.get("version") or "")

failures = []
if api_version != expected:
    failures.append(f"API version {api_version!r}, expected {expected!r}")
if frontend_version != expected:
    failures.append(f"frontend version {frontend_version!r}, expected {expected!r}")
if api_version != frontend_version:
    failures.append(f"API/frontend mismatch: {api_version!r} != {frontend_version!r}")

if failures:
    print("Deployed version check: FAIL")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)

print(f"Version parity: PASS (v{expected})")
PY

if ! tr -d '\r' < "$tmp_dir/index.headers" | grep -Eiq '^Cache-Control:.*(no-store|no-cache)'; then
    echo "Deployed version check: FAIL - index.html is cacheable" >&2
    exit 1
fi

asset_path="$(grep -Eo "/assets/[^\"'[:space:]]+\\.js" "$tmp_dir/index.html" | head -1 || true)"
if [ -z "$asset_path" ]; then
    echo "Deployed version check: FAIL - hashed frontend asset not found" >&2
    exit 1
fi

curl -fsS -I "$base_url$asset_path" > "$tmp_dir/asset.headers"
if ! tr -d '\r' < "$tmp_dir/asset.headers" | grep -Eiq '^Cache-Control:.*immutable'; then
    echo "Deployed version check: FAIL - hashed asset is not immutable" >&2
    exit 1
fi

echo "Cache policy: PASS (HTML no-store, hashed assets immutable)"
echo "Deployed version check: PASS"
