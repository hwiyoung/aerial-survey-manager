#!/usr/bin/env bash
# Opt-in hold/unhold for the currently installed kernel/NVIDIA package stack.

set -euo pipefail

ACTION=""
ASSUME_YES=false

usage() {
    cat <<'EOF'
Usage:
  sudo ./scripts/pin-gpu-stack.sh --hold [--yes]
  sudo ./scripts/pin-gpu-stack.sh --unhold [--yes]
  ./scripts/pin-gpu-stack.sh --list

Purpose:
  Hold or unhold the installed kernel/NVIDIA stack as an explicit operator
  choice. This can prevent kernel/NVIDIA module mismatch after unattended
  upgrades, but it can also delay kernel security updates.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --hold|--unhold|--list)
            ACTION="$1"
            ;;
        --yes|-y)
            ASSUME_YES=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [ -z "$ACTION" ]; then
    usage >&2
    exit 2
fi

installed_packages() {
    dpkg-query -W -f='${binary:Package}\t${db:Status-Abbrev}\n' \
        'linux-image-*' \
        'linux-headers-*' \
        'linux-generic-hwe-*' \
        'linux-image-generic-hwe-*' \
        'linux-headers-generic-hwe-*' \
        'linux-modules-nvidia-*' \
        'nvidia-driver-*' \
        2>/dev/null \
        | awk '$2 ~ /^ii/ {print $1}' \
        | sort -u
}

packages="$(installed_packages)"

if [ -z "$packages" ]; then
    echo "No installed kernel/NVIDIA packages matched the hold list."
    exit 1
fi

echo "Current kernel: $(uname -r)"
echo ""
echo "Target packages:"
printf '%s\n' "$packages" | sed 's/^/  - /'
echo ""

if [ "$ACTION" = "--list" ]; then
    apt-mark showhold | grep -E '^(linux-image-|linux-headers-|linux-generic-hwe-|linux-image-generic-hwe-|linux-headers-generic-hwe-|linux-modules-nvidia-|nvidia-driver-)' || true
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: $ACTION requires root. Re-run with sudo." >&2
    exit 1
fi

cat <<'EOF'
WARNING:
  Holding kernel/NVIDIA packages can prevent the mismatch where the running
  kernel has no matching linux-modules-nvidia package. It can also delay kernel
  and driver security updates. Use this only as an explicit operations choice,
  and schedule a maintenance window to unhold/update/reboot later.
EOF

if [ "$ASSUME_YES" != true ]; then
    read -r -p "Continue with ${ACTION#--}? (y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

case "$ACTION" in
    --hold)
        printf '%s\n' "$packages" | xargs apt-mark hold
        ;;
    --unhold)
        printf '%s\n' "$packages" | xargs apt-mark unhold
        ;;
esac

echo "Done."
