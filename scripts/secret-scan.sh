#!/bin/sh
# Scan the repository for credentials / API keys before a push.
# Usage: scripts/secret-scan.sh [--staged]
#   --staged  scan only staged changes (used by pre-commit hook)
# Exit code 1 if any secret pattern is found.
set -eu

PATTERN='sk-[A-Za-z0-9_-]{20,}|syn_[A-Za-z0-9_-]{20,}|[0-9]{8,10}:AA[A-Za-z0-9_-]{33,}|xox[baprs]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{36,}|AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----'

scan_files() {
    found=0
    for f in "$@"; do
        [ -f "$f" ] || continue
        case "$f" in
            *.lock|*.png|*.jpg|*.ico|*.gz|*.deb|*.rpm|*.pkg.tar.zst) continue ;;
        esac
        if grep -InE "$PATTERN" "$f" 2>/dev/null | grep -vE 'syn_test|123:ABC|1234567890'; then
            echo "POTENTIAL SECRET in: $f" >&2
            found=1
        fi
    done
    return $found
}

if [ "${1:-}" = "--staged" ]; then
    files=$(git diff --cached --name-only --diff-filter=ACM)
    [ -z "$files" ] && exit 0
    # shellcheck disable=SC2086
    scan_files $files
else
    cd "$(dirname "$0")/.."
    # All tracked files plus worktree, excluding .git
    files=$(git ls-files; git ls-files --others --exclude-standard)
    [ -z "$files" ] && exit 0
    # shellcheck disable=SC2086
    scan_files $files
fi
