#!/usr/bin/env bash
# Build all pkger package images locally.
#
# pkger 0.11.0 quirk: after building a custom image it immediately does
# `FROM <image-name>:latest`, but applying the :latest tag is racy — the build
# intermittently fails with "pull access denied". Workaround: pre-build and
# tag each custom image with docker ourselves (fast — pkger then reuses it).
#
# Usage: scripts/build-all-packages.sh [image ...]
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGES=(debian-13 ubuntu-2404 ubuntu-2604 fedora-43 fedora-44 rhel-8 rhel-9 opensuse-tumbleweed arch)
if [ $# -gt 0 ]; then
    IMAGES=("$@")
fi

mkdir -p dist .pkger-logs

for img in "${IMAGES[@]}"; do
    echo "=== pre-tagging $img ==="
    docker build -q -t "$img:latest" "images/$img" >/dev/null
    echo "=== building $img package ==="
    ./bin/pkger -c .pkger.yml build -i "$img" -- synthetic-usage-awareness
done

echo "=== artifacts ==="
find dist -type f | sort
