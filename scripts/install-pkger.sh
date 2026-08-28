#!/bin/sh
# Install pkger binary into ./bin (CI or local use).
# Usage: scripts/install-pkger.sh [version]   (default: 0.11.0)
set -eu

VERSION="${1:-0.11.0}"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) SUFFIX="x86_64-unknown-linux" ;;
    aarch64|arm64) SUFFIX="aarch64-unknown-linux" ;;
    *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

URL="https://github.com/vv9k/pkger/releases/download/${VERSION}/pkger-${VERSION}-${SUFFIX}.tar.gz"
echo "Downloading pkger ${VERSION} (${SUFFIX})..."
curl -fsSL "$URL" | tar -xz -C "$WORK"

# The tarball nests the binary in pkger-<version>/ (or directly at the root,
# depending on release) — find the actual binary.
BIN="$(find "$WORK" -type f -name pkger | head -n1)"
if [ -z "$BIN" ]; then
    echo "pkger binary not found in the archive" >&2
    exit 1
fi

mkdir -p bin
install -m 0755 "$BIN" bin/pkger
./bin/pkger --version
