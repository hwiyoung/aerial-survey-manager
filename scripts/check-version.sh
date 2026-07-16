#!/bin/bash
#
# Verify that every published version surface matches the root VERSION file.
#

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f VERSION ]; then
    echo "Version check: FAIL - VERSION file is missing" >&2
    exit 1
fi

VERSION_VALUE=$(tr -d '[:space:]' < VERSION)

python3 - "$VERSION_VALUE" <<'PY'
import json
import re
import sys
from pathlib import Path

version = sys.argv[1]
semver = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
failures = []

if not semver.fullmatch(version):
    failures.append(f"VERSION is not valid SemVer: {version!r}")

package = json.loads(Path("package.json").read_text(encoding="utf-8"))
package_lock = json.loads(Path("package-lock.json").read_text(encoding="utf-8"))
runtime_text = Path("backend/app/version.py").read_text(encoding="utf-8")
user_manual = Path("docs/USER_MANUAL.md").read_text(encoding="utf-8")
changelog = Path("docs/CHANGELOG.md").read_text(encoding="utf-8")

checks = {
    "package.json": package.get("version"),
    "package-lock.json": package_lock.get("version"),
    "package-lock.json root package": package_lock.get("packages", {}).get("", {}).get("version"),
}
for source, actual in checks.items():
    if actual != version:
        failures.append(f"{source}: {actual!r}, expected {version!r}")

runtime_match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"$', runtime_text, re.MULTILINE)
if not runtime_match or runtime_match.group(1) != version:
    actual = runtime_match.group(1) if runtime_match else None
    failures.append(f"backend/app/version.py: {actual!r}, expected {version!r}")

if f"> 버전: v{version}" not in user_manual:
    failures.append(f"docs/USER_MANUAL.md: missing v{version}")

first_release_heading = next(
    (line for line in changelog.splitlines() if line.startswith("## ")),
    "",
)
if not first_release_heading.startswith(f"## v{version} "):
    failures.append(
        f"docs/CHANGELOG.md: first release heading {first_release_heading!r}, "
        f"expected v{version}"
    )

if failures:
    print("Version check: FAIL")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)

print(f"Version check: PASS (v{version})")
PY
