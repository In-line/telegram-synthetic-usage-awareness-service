#!/bin/sh
# Release checklist: secrets must be clean, then tag.
#   ./scripts/release.sh v1.0.0
set -eu

TAG="${1:-}"
if [ -z "$TAG" ]; then
    echo "Usage: $0 <tag>   e.g. $0 v1.0.0" >&2
    exit 1
fi

echo "Running secret scan..."
./scripts/secret-scan.sh

git tag "$TAG"
git push origin "$TAG"
echo "Tag $TAG pushed — the Release workflow will build and publish packages."
